#!/usr/bin/env python3

import argparse
import json
import time
import threading
from datetime import datetime, timedelta
from typing import Dict, Optional
import paho.mqtt.client as mqtt
from flask import Flask, render_template, jsonify, send_from_directory
import os
from dotenv import load_dotenv

class MQTTHealthChecker:
    def __init__(self, broker_host: str = "localhost", broker_port: int = 1883, 
                 broker_username: Optional[str] = None, broker_password: Optional[str] = None,
                 topics_file: str = "topics.json"):
        self.broker_host = broker_host
        self.broker_port = broker_port
        self.broker_username = broker_username
        self.broker_password = broker_password
        self.topics_file = topics_file
        self.topic_timestamps: Dict[str, datetime] = {}
        self.topic_counters: Dict[str, int] = {}
        self.topic_message_history: Dict[str, list] = {}  # Store last N timestamps for each topic
        self.topics: list = []
        self.topic_descriptions: Dict[str, str] = {}
        self.topic_types: Dict[str, str] = {}
        self.max_history_size = 100  # Keep last 100 timestamps for average calculation
        self.client: Optional[mqtt.Client] = None
        self.lock = threading.Lock()
        
        self.load_topics()
        self.setup_mqtt()
        
    def load_topics(self):
        """Load topics from JSON configuration file"""
        try:
            with open(self.topics_file, 'r') as f:
                config = json.load(f)
                topics_data = config.get('topics', [])
                
                self.topics = []
                self.topic_descriptions = {}
                self.topic_types = {}
                
                for item in topics_data:
                    if isinstance(item, str):
                        # Legacy format: just topic string
                        topic = item
                        self.topics.append(topic)
                    elif isinstance(item, dict):
                        # New format: object with topic and optional description/type
                        topic = item.get('topic', '')
                        description = item.get('description', '')
                        topic_type = item.get('type', '')
                        if topic:
                            self.topics.append(topic)
                            if description:
                                self.topic_descriptions[topic] = description
                            if topic_type:
                                self.topic_types[topic] = topic_type
                        
        except FileNotFoundError:
            print(f"Topics file {self.topics_file} not found. Using empty topics list.")
            self.topics = []
            self.topic_descriptions = {}
            self.topic_types = {}
            self.topic_message_history = {}
        except json.JSONDecodeError:
            print(f"Error parsing {self.topics_file}. Using empty topics list.")
            self.topics = []
            self.topic_descriptions = {}
            self.topic_types = {}
            self.topic_message_history = {}
    
    def setup_mqtt(self):
        """Setup MQTT client and callbacks"""
        self.client = mqtt.Client()
        
        # Set username and password if provided
        if self.broker_username and self.broker_password:
            self.client.username_pw_set(self.broker_username, self.broker_password)
            
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.client.on_disconnect = self.on_disconnect
        
    def on_connect(self, client, userdata, flags, rc):
        """Callback for when client connects to MQTT broker"""
        if rc == 0:
            print(f"Connected to MQTT broker at {self.broker_host}:{self.broker_port}")
            for topic in self.topics:
                client.subscribe(topic)
                print(f"Subscribed to topic: {topic}")
        else:
            print(f"Failed to connect to MQTT broker. Return code: {rc}")
    
    def on_message(self, client, userdata, msg):
        """Callback for when a message is received"""
        topic = msg.topic
        current_time = datetime.now()
        
        with self.lock:
            self.topic_timestamps[topic] = current_time
            self.topic_counters[topic] = self.topic_counters.get(topic, 0) + 1
            
            # Add timestamp to message history for average calculation
            if topic not in self.topic_message_history:
                self.topic_message_history[topic] = []
            
            self.topic_message_history[topic].append(current_time)
            
            # Keep only the last N timestamps to limit memory usage
            if len(self.topic_message_history[topic]) > self.max_history_size:
                self.topic_message_history[topic] = self.topic_message_history[topic][-self.max_history_size:]
        
        print(f"Received message on topic: {topic}")
    
    def on_disconnect(self, client, userdata, rc):
        """Callback for when client disconnects"""
        print("Disconnected from MQTT broker")
        
    def start_mqtt(self):
        """Start MQTT client in background thread"""
        def mqtt_loop():
            try:
                self.client.connect(self.broker_host, self.broker_port, 60)
                self.client.loop_forever()
            except Exception as e:
                print(f"MQTT connection error: {e}")
        
        mqtt_thread = threading.Thread(target=mqtt_loop, daemon=True)
        mqtt_thread.start()
        
    def get_status_data(self):
        """Get current status data for all topics"""
        current_time = datetime.now()
        status_data = []
        
        with self.lock:
            for topic in self.topics:
                if topic in self.topic_timestamps:
                    last_seen = self.topic_timestamps[topic]
                    time_diff = current_time - last_seen
                    status = "healthy" if time_diff < timedelta(hours=1) else "unhealthy"
                else:
                    last_seen = None
                    time_diff = None
                    status = "never_seen"
                
                message_count = self.topic_counters.get(topic, 0)
                display_name = self.topic_descriptions.get(topic, topic)
                topic_type = self.topic_types.get(topic, 'unknown')
                
                # Calculate average time between messages
                avg_interval = self._calculate_average_interval(topic)
                
                status_data.append({
                    'topic': topic,
                    'display_name': display_name,
                    'type': topic_type,
                    'last_seen': last_seen.strftime('%Y-%m-%d %H:%M:%S') if last_seen else 'Never',
                    'time_since': str(time_diff).split('.')[0] if time_diff else 'Never',
                    'message_count': message_count,
                    'avg_interval': avg_interval,
                    'status': status
                })
        
        return status_data
    
    def _calculate_average_interval(self, topic: str) -> str:
        """Calculate average time between messages for a topic"""
        if topic not in self.topic_message_history:
            return "No data"
        
        timestamps = self.topic_message_history[topic]
        if len(timestamps) < 2:
            return "No data"
        
        # Calculate intervals between consecutive messages
        intervals = []
        for i in range(1, len(timestamps)):
            interval = (timestamps[i] - timestamps[i-1]).total_seconds()
            intervals.append(interval)
        
        if not intervals:
            return "No data"
        
        # Calculate average interval in seconds
        avg_seconds = sum(intervals) / len(intervals)
        
        # Format as human readable string
        if avg_seconds < 60:
            return f"{avg_seconds:.1f}s"
        elif avg_seconds < 3600:
            minutes = avg_seconds / 60
            return f"{minutes:.1f}m"
        elif avg_seconds < 86400:
            hours = avg_seconds / 3600
            return f"{hours:.1f}h"
        else:
            days = avg_seconds / 86400
            return f"{days:.1f}d"

# Flask web application
app = Flask(__name__)
health_checker = None

@app.route('/')
def index():
    """Main page showing topic health status"""
    return render_template('index.html')

@app.route('/api/status')
def get_status():
    """API endpoint to get current status data"""
    if health_checker:
        return jsonify(health_checker.get_status_data())
    return jsonify([])

@app.route('/static/icons/<filename>')
def serve_icon(filename):
    """Serve icon files from the icons directory"""
    return send_from_directory('icons', filename)

@app.route('/metrics')
def get_metrics():
    """Prometheus metrics endpoint"""
    if not health_checker:
        return "# No health checker initialized\n", 200, {'Content-Type': 'text/plain'}
    
    status_data = health_checker.get_status_data()
    metrics_lines = []
    
    # Add help and type information
    metrics_lines.append("# HELP mqtt_topic_last_seen_timestamp Unix timestamp of last message received for each topic")
    metrics_lines.append("# TYPE mqtt_topic_last_seen_timestamp gauge")
    metrics_lines.append("# HELP mqtt_topic_message_count Total number of messages received for each topic")
    metrics_lines.append("# TYPE mqtt_topic_message_count counter")
    metrics_lines.append("# HELP mqtt_topic_healthy Whether the topic is considered healthy (1) or not (0)")
    metrics_lines.append("# TYPE mqtt_topic_healthy gauge")
    metrics_lines.append("# HELP mqtt_topic_avg_interval_seconds Average interval between messages in seconds")
    metrics_lines.append("# TYPE mqtt_topic_avg_interval_seconds gauge")
    
    current_time = datetime.now()
    
    for topic_data in status_data:
        topic = topic_data['topic']
        # Sanitize topic name for Prometheus (replace invalid characters with underscores)
        safe_topic = topic.replace('/', '_').replace('-', '_').replace('.', '_').replace(':', '_').replace(' ', '_')
        display_name = topic_data['display_name']
        topic_type = topic_data['type']
        message_count = topic_data['message_count']
        status = topic_data['status']
        
        # Calculate timestamp for last seen
        if topic_data['last_seen'] != 'Never':
            last_seen_dt = datetime.strptime(topic_data['last_seen'], '%Y-%m-%d %H:%M:%S')
            last_seen_timestamp = last_seen_dt.timestamp()
        else:
            last_seen_timestamp = 0
        
        # Convert average interval to seconds
        avg_interval_str = topic_data['avg_interval']
        avg_interval_seconds = 0
        if avg_interval_str != "No data":
            if avg_interval_str.endswith('s'):
                avg_interval_seconds = float(avg_interval_str[:-1])
            elif avg_interval_str.endswith('m'):
                avg_interval_seconds = float(avg_interval_str[:-1]) * 60
            elif avg_interval_str.endswith('h'):
                avg_interval_seconds = float(avg_interval_str[:-1]) * 3600
            elif avg_interval_str.endswith('d'):
                avg_interval_seconds = float(avg_interval_str[:-1]) * 86400
        
        # Labels for metrics
        labels = f'topic="{topic}",display_name="{display_name}",type="{topic_type}"'
        
        # Last seen timestamp metric
        metrics_lines.append(f'mqtt_topic_last_seen_timestamp{{{labels}}} {last_seen_timestamp}')
        
        # Message count metric
        metrics_lines.append(f'mqtt_topic_message_count{{{labels}}} {message_count}')
        
        # Health status metric (1 for healthy, 0 for unhealthy/never_seen)
        healthy_value = 1 if status == "healthy" else 0
        metrics_lines.append(f'mqtt_topic_healthy{{{labels}}} {healthy_value}')
        
        # Average interval metric
        if avg_interval_seconds > 0:
            metrics_lines.append(f'mqtt_topic_avg_interval_seconds{{{labels}}} {avg_interval_seconds}')
    
    # Join all metrics with newlines and add final newline
    metrics_content = '\n'.join(metrics_lines) + '\n'
    
    return metrics_content, 200, {'Content-Type': 'text/plain'}

def main():
    global health_checker
    
    # Load environment variables from .env file
    load_dotenv()
    
    # Parse command line arguments with environment variable defaults
    parser = argparse.ArgumentParser(description='MQTT IoT Health Checker')
    parser.add_argument('--host', default=os.getenv('MQTT_HOST', 'localhost'), 
                        help='MQTT broker hostname or IP (default: localhost or MQTT_HOST env var)')
    parser.add_argument('--port', type=int, default=int(os.getenv('MQTT_PORT', '1883')),
                        help='MQTT broker port (default: 1883 or MQTT_PORT env var)')
    parser.add_argument('--user', default=os.getenv('MQTT_USER'),
                        help='MQTT broker username (default: MQTT_USER env var)')
    parser.add_argument('--password', default=os.getenv('MQTT_PASSWORD'),
                        help='MQTT broker password (default: MQTT_PASSWORD env var)')
    parser.add_argument('--topics-file', default=os.getenv('MQTT_TOPICS_FILE', 'topics.json'),
                        help='JSON file containing topics to monitor (default: topics.json or MQTT_TOPICS_FILE env var)')
    
    args = parser.parse_args()
    
    # Initialize MQTT health checker with command line arguments
    health_checker = MQTTHealthChecker(
        broker_host=args.host,
        broker_port=args.port,
        broker_username=args.user,
        broker_password=args.password,
        topics_file=args.topics_file
    )
    
    # Start MQTT client
    health_checker.start_mqtt()
    
    # Give MQTT client time to connect
    time.sleep(2)
    
    # Start Flask web server
    print("Starting web server on http://localhost:5000")
    app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=False)

if __name__ == "__main__":
    main()
