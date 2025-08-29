docker build -t g8keeperzuul/mqtt_iot_healthcheck .
docker save -o /tmp/mqtt_iot_healthcheck.image.tar g8keeperzuul/mqtt_iot_healthcheck:latest

# On target system:
#docker load -i /tmp/mqtt_iot_healthcheck.image.tar
#docker images

# Mount a read-only volume of the contents of a local /config directory containing topics.json to /config in the container.
# Docker compose YAML snippet:

# Listens on topics of multiple devices and parses message for Chime published to its display command topic. 
#  mqtt_iot_healthcheck:
#    container_name: mqtt_iot_healthcheck
#    image: g8keeperzuul/mqtt_iot_healthcheck
#    mem_limit: 128m
#    cpus: 1.0
#    networks:
#      - homeautomation_network
#    ports:
#      - 5000:5000
#    volumes:
#      - /etc/timezone:/etc/timezone:ro
#      - /etc/localtime:/etc/localtime:ro
#      - /home/homeassistant/containers/mqtt_iot_healthcheck/config:/config:ro
#    restart: unless-stopped
#    attach: false
#    command: --host mosquitto --port 1883 --user mqtt-user --password mqtt-password --topics-file /config/topics.json
#    depends_on:
#      - mosquitto
