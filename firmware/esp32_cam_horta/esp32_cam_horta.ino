#include <Arduino.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <WiFiClientSecure.h>
#include <Preferences.h>
#include <ArduinoJson.h>
#include "esp_camera.h"
#include "esp_http_server.h"
#include "img_converters.h"
#include "camera_pins.h"
#include "wifi_config.h"

namespace {
httpd_handle_t cameraServer = nullptr;
constexpr char STREAM_BOUNDARY[] = "horta-camera-boundary";
unsigned long lastPhotoUploadAt = 0;
HardwareSerial provisionSerial(2);
Preferences wifiPreferences;
String provisionLine;
unsigned long lastWifiAttemptAt = 0;
bool servicesStarted = false;

bool loadWifiCredentials(String& ssid, String& password) {
  wifiPreferences.begin("horta-wifi", true);
  ssid = wifiPreferences.getString("ssid", "");
  password = wifiPreferences.getString("password", "");
  wifiPreferences.end();
  return !ssid.isEmpty();
}

void saveWifiCredentials(const String& ssid, const String& password) {
  wifiPreferences.begin("horta-wifi", false);
  wifiPreferences.putString("ssid", ssid);
  wifiPreferences.putString("password", password);
  wifiPreferences.end();
}

void sendProvisionAck(const char* type) {
  JsonDocument response;
  response["type"] = type;
  response["status"] = "ok";
  serializeJson(response, provisionSerial);
  provisionSerial.write('\n');
  provisionSerial.flush();
}

void connectStoredWifi() {
  String ssid, password;
  if (!loadWifiCredentials(ssid, password)) {
    Serial.println("Wi-Fi nao configurado; aguardando ESP8266 pela UART");
    return;
  }
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  WiFi.begin(ssid.c_str(), password.c_str());
  lastWifiAttemptAt = millis();
  Serial.printf("Conectando ao SSID salvo: %s\n", ssid.c_str());
}

void handleProvisionMessage(const String& line) {
  JsonDocument message;
  if (deserializeJson(message, line)) {
    Serial.println("Provisionamento ignorado: JSON invalido");
    return;
  }
  const char* type = message["type"] | "";
  if (!strcmp(type, "wifi_config")) {
    String ssid = message["ssid"] | "";
    String password = message["password"] | "";
    if (ssid.isEmpty() || ssid.length() > 32 || password.length() > 63) {
      Serial.println("Provisionamento ignorado: credenciais fora dos limites");
      return;
    }
    saveWifiCredentials(ssid, password);
    sendProvisionAck("wifi_ack");
    Serial.printf("Nova configuracao Wi-Fi salva para SSID: %s\n", ssid.c_str());
    delay(200);
    ESP.restart();
  }
  if (!strcmp(type, "wifi_reset")) {
    wifiPreferences.begin("horta-wifi", false);
    wifiPreferences.clear();
    wifiPreferences.end();
    sendProvisionAck("wifi_reset_ack");
    Serial.println("Credenciais Wi-Fi apagadas");
    delay(200);
    WiFi.disconnect(true, true);
    ESP.restart();
  }
}

void processProvisionSerial() {
  while (provisionSerial.available()) {
    char value = static_cast<char>(provisionSerial.read());
    if (value == '\n') {
      if (!provisionLine.isEmpty()) handleProvisionMessage(provisionLine);
      provisionLine = "";
    } else if (value != '\r') {
      if (provisionLine.length() < 384) provisionLine += value;
      else provisionLine = "";
    }
  }
}

void addCommonHeaders(httpd_req_t* request) {
  // Leitura local sem credenciais. Restrinja a rede Wi-Fi a dispositivos confiaveis.
  httpd_resp_set_hdr(request, "Access-Control-Allow-Origin", "*");
  httpd_resp_set_hdr(request, "Cache-Control", "no-store, no-cache, must-revalidate");
  httpd_resp_set_hdr(request, "X-Content-Type-Options", "nosniff");
}

esp_err_t rootHandler(httpd_req_t* request) {
  static const char page[] PROGMEM =
      "<!doctype html><html lang='pt-br'><meta charset='utf-8'>"
      "<meta name='viewport' content='width=device-width'>"
      "<title>Camera da Horta</title><body><h1>Camera da Horta</h1>"
      "<p><a href='/capture'>Capturar JPEG</a> | <a href='/stream'>Abrir stream MJPEG</a></p>"
      "<img src='/stream' style='max-width:100%;height:auto' alt='Stream da horta'></body></html>";
  addCommonHeaders(request);
  httpd_resp_set_type(request, "text/html; charset=utf-8");
  return httpd_resp_send(request, page, HTTPD_RESP_USE_STRLEN);
}

esp_err_t captureHandler(httpd_req_t* request) {
  camera_fb_t* frame = esp_camera_fb_get();
  if (!frame) {
    httpd_resp_send_err(request, HTTPD_500_INTERNAL_SERVER_ERROR, "Falha ao capturar imagem");
    return ESP_FAIL;
  }

  addCommonHeaders(request);
  httpd_resp_set_type(request, "image/jpeg");
  esp_err_t result = ESP_OK;
  if (frame->format == PIXFORMAT_JPEG) {
    result = httpd_resp_send(request, reinterpret_cast<const char*>(frame->buf), frame->len);
  } else {
    uint8_t* jpeg = nullptr;
    size_t jpegLength = 0;
    if (!frame2jpg(frame, 80, &jpeg, &jpegLength)) {
      result = ESP_FAIL;
    } else {
      result = httpd_resp_send(request, reinterpret_cast<const char*>(jpeg), jpegLength);
      free(jpeg);
    }
  }
  esp_camera_fb_return(frame);
  return result;
}

esp_err_t streamHandler(httpd_req_t* request) {
  char contentType[96];
  snprintf(contentType, sizeof(contentType), "multipart/x-mixed-replace;boundary=%s", STREAM_BOUNDARY);
  addCommonHeaders(request);
  httpd_resp_set_type(request, contentType);

  while (true) {
    camera_fb_t* frame = esp_camera_fb_get();
    if (!frame) return ESP_FAIL;

    uint8_t* jpeg = frame->buf;
    size_t jpegLength = frame->len;
    bool converted = false;
    if (frame->format != PIXFORMAT_JPEG) {
      converted = frame2jpg(frame, 80, &jpeg, &jpegLength);
      if (!converted) {
        esp_camera_fb_return(frame);
        return ESP_FAIL;
      }
    }

    char header[128];
    int headerLength = snprintf(header, sizeof(header),
        "--%s\r\nContent-Type: image/jpeg\r\nContent-Length: %u\r\n\r\n",
        STREAM_BOUNDARY, static_cast<unsigned>(jpegLength));
    esp_err_t result = httpd_resp_send_chunk(request, header, headerLength);
    if (result == ESP_OK) {
      result = httpd_resp_send_chunk(request, reinterpret_cast<const char*>(jpeg), jpegLength);
    }
    if (result == ESP_OK) result = httpd_resp_send_chunk(request, "\r\n", 2);

    if (converted) free(jpeg);
    esp_camera_fb_return(frame);
    if (result != ESP_OK) break;
  }
  return ESP_OK;
}

bool startCamera() {
  camera_config_t config = {};
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer = LEDC_TIMER_0;
  config.pin_d0 = Y2_GPIO_NUM;
  config.pin_d1 = Y3_GPIO_NUM;
  config.pin_d2 = Y4_GPIO_NUM;
  config.pin_d3 = Y5_GPIO_NUM;
  config.pin_d4 = Y6_GPIO_NUM;
  config.pin_d5 = Y7_GPIO_NUM;
  config.pin_d6 = Y8_GPIO_NUM;
  config.pin_d7 = Y9_GPIO_NUM;
  config.pin_xclk = XCLK_GPIO_NUM;
  config.pin_pclk = PCLK_GPIO_NUM;
  config.pin_vsync = VSYNC_GPIO_NUM;
  config.pin_href = HREF_GPIO_NUM;
  config.pin_sccb_sda = SIOD_GPIO_NUM;
  config.pin_sccb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn = PWDN_GPIO_NUM;
  config.pin_reset = RESET_GPIO_NUM;
  config.xclk_freq_hz = 20000000;
  config.pixel_format = PIXFORMAT_JPEG;
  config.frame_size = psramFound() ? FRAMESIZE_SVGA : FRAMESIZE_VGA;
  config.jpeg_quality = psramFound() ? 10 : 12;
  config.fb_count = psramFound() ? 2 : 1;
  config.grab_mode = psramFound() ? CAMERA_GRAB_LATEST : CAMERA_GRAB_WHEN_EMPTY;
  config.fb_location = psramFound() ? CAMERA_FB_IN_PSRAM : CAMERA_FB_IN_DRAM;

  esp_err_t error = esp_camera_init(&config);
  if (error != ESP_OK) {
    Serial.printf("Falha ao iniciar camera: 0x%x\n", error);
    return false;
  }

  sensor_t* sensor = esp_camera_sensor_get();
  if (sensor) Serial.printf("Sensor detectado, PID: 0x%04x\n", sensor->id.PID);
  return true;
}

bool startHttpServer() {
  httpd_config_t config = HTTPD_DEFAULT_CONFIG();
  config.max_uri_handlers = 4;
  if (httpd_start(&cameraServer, &config) != ESP_OK) return false;

  const httpd_uri_t root = {"/", HTTP_GET, rootHandler, nullptr};
  const httpd_uri_t capture = {"/capture", HTTP_GET, captureHandler, nullptr};
  const httpd_uri_t stream = {"/stream", HTTP_GET, streamHandler, nullptr};
  return httpd_register_uri_handler(cameraServer, &root) == ESP_OK &&
         httpd_register_uri_handler(cameraServer, &capture) == ESP_OK &&
         httpd_register_uri_handler(cameraServer, &stream) == ESP_OK;
}

void uploadPhoto() {
  if (WiFi.status() != WL_CONNECTED) return;
  camera_fb_t* frame = esp_camera_fb_get();
  if (!frame) {
    Serial.println("Upload: falha ao capturar imagem");
    return;
  }
  if (frame->format != PIXFORMAT_JPEG) {
    Serial.println("Upload: frame nao e JPEG");
    esp_camera_fb_return(frame);
    return;
  }

  HTTPClient http;
  WiFiClient plain;
  WiFiClientSecure secure;
  String url = String(API_BASE_URL) + "/api/device/photo/";
  bool started = false;
  if (url.startsWith("https://")) {
    if (strlen(HTTPS_ROOT_CA) < 40) {
      Serial.println("Upload HTTPS recusado: configure HTTPS_ROOT_CA");
      esp_camera_fb_return(frame);
      return;
    }
    secure.setCACert(HTTPS_ROOT_CA);
    started = http.begin(secure, url);
  } else {
    started = http.begin(plain, url);
  }
  if (!started) {
    esp_camera_fb_return(frame);
    return;
  }
  http.setTimeout(15000);
  http.addHeader("Authorization", String("Device ") + DEVICE_TOKEN);
  http.addHeader("X-Device-ID", DEVICE_ID);
  http.addHeader("Content-Type", "image/jpeg");
  int status = http.POST(frame->buf, frame->len);
  Serial.printf("Upload da foto: HTTP %d\n", status);
  http.end();
  esp_camera_fb_return(frame);
}
}  // namespace

void setup() {
  Serial.begin(115200);
  provisionSerial.begin(9600, SERIAL_8N1, 13, 14);
  Serial.setDebugOutput(true);
  Serial.println("\nIniciando ESP32-CAM da Horta (AI Thinker)...");

  if (!startCamera()) return;

  connectStoredWifi();
}

void loop() {
  processProvisionSerial();
  if (WiFi.status() == WL_CONNECTED && !servicesStarted) {
    Serial.print("Wi-Fi conectado. IP da camera: http://");
    Serial.println(WiFi.localIP());
    servicesStarted = startHttpServer();
    Serial.println(servicesStarted ? "HTTP ativo: /, /capture e /stream" : "Falha ao iniciar HTTP");
    uploadPhoto();
    lastPhotoUploadAt = millis();
  }
  if (WiFi.status() != WL_CONNECTED && millis() - lastWifiAttemptAt >= 15000UL) {
    lastWifiAttemptAt = millis();
    connectStoredWifi();
  }
  if (millis() - lastPhotoUploadAt >= PHOTO_INTERVAL_MS) {
    lastPhotoUploadAt = millis();
    uploadPhoto();
  }
  delay(20);
}
