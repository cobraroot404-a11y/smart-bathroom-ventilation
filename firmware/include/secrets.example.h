#pragma once

// Copy this file to firmware/include/secrets.h (git-ignored - see
// .gitignore) and fill in real values. Never commit secrets.h.

#define WIFI_SSID "YOUR_WIFI_SSID"
#define WIFI_PASSWORD "YOUR_WIFI_PASSWORD"

#define MQTT_HOST "192.168.1.10"
#define MQTT_PORT 1883
#define MQTT_USERNAME "bathroom-vent-device"
#define MQTT_PASSWORD "CHANGE_ME_DEVICE_PASSWORD"
#define MQTT_USE_TLS false
