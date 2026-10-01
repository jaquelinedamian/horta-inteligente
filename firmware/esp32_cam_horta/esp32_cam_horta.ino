#include <Arduino.h>
#include <WiFi.h>
#include <WiFiManager.h>
#include <HTTPClient.h>
#include <WiFiClientSecure.h>
#include <time.h>
#include "esp_camera.h"
#include "esp_http_server.h"
#include "img_converters.h"
#include "camera_pins.h"
#include "wifi_config.h"

namespace {
httpd_handle_t cameraServer = nullptr;
constexpr char STREAM_BOUNDARY[] = "horta-camera-boundary";
unsigned long lastPhotoUploadAt = 0;
unsigned long lastWifiAttemptAt = 0;
bool servicesStarted = false;
bool clockSynchronized = false;
String serialCommand;
constexpr time_t MIN_VALID_EPOCH = 1700000000;
constexpr unsigned long NTP_TIMEOUT_MS = 30000UL;

void processSerialCommand();

String wifiAccessPointName() {
  uint64_t chipId = ESP.getEfuseMac();
  char suffix[9];
  snprintf(suffix, sizeof(suffix), "%08X", static_cast<uint32_t>(chipId));
  return String("Horta-Camera-") + suffix;
}

bool configureWifi() {
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  WiFiManager manager;
  manager.setDebugOutput(true);
  String accessPoint = wifiAccessPointName();
  Serial.printf("Conectando ao Wi-Fi salvo; portal alternativo: %s em 192.168.4.1\n",
                accessPoint.c_str());
  bool connected = manager.autoConnect(accessPoint.c_str());
  if (!connected) {
    Serial.println("Falha no provisionamento Wi-Fi");
  } else {
    Serial.println("Wi-Fi conectado!");
    Serial.printf("SSID: %s\n", WiFi.SSID().c_str());
    Serial.printf("IP: %s\n", WiFi.localIP().toString().c_str());
    Serial.printf("RSSI: %d dBm\n", WiFi.RSSI());
  }
  return connected;
}

bool synchronizeClock() {
  Serial.println("Sincronizando horario...");
  configTime(0, 0, "pool.ntp.org", "time.google.com", "time.cloudflare.com");
  const unsigned long startedAt = millis();
  while (time(nullptr) < MIN_VALID_EPOCH && millis() - startedAt < NTP_TIMEOUT_MS) {
    processSerialCommand();
    delay(250);
  }
  const time_t now = time(nullptr);
  if (now < MIN_VALID_EPOCH) {
    Serial.println("Erro: horario nao sincronizado dentro do timeout; HTTPS sera adiado");
    return false;
  }
  char formatted[32];
  struct tm utcTime;
  gmtime_r(&now, &utcTime);
  strftime(formatted, sizeof(formatted), "%Y-%m-%dT%H:%M:%SZ", &utcTime);
  Serial.printf("Horario sincronizado: %s\n", formatted);
  return true;
}

void resetOwnWifi() {
  WiFiManager manager;
  manager.resetSettings();
  WiFi.disconnect(true, true);
  Serial.println("Wi-Fi da camera apagado; reiniciando no portal proprio");
  delay(500);
  ESP.restart();
}

void processSerialCommand() {
  while (Serial.available()) {
    char value = static_cast<char>(Serial.read());
    if (value == '\n') {
      serialCommand.trim();
      if (serialCommand == "RESET_WIFI") resetOwnWifi();
      serialCommand = "";
    } else if (value != '\r') {
      if (serialCommand.length() < 32) serialCommand += value;
      else serialCommand = "";
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
  const bool hasPsram = psramFound();
  config.frame_size = hasPsram ? FRAMESIZE_SVGA : FRAMESIZE_VGA;
  config.jpeg_quality = hasPsram ? 10 : 12;
  // Um unico buffer evita a fila de frames que provocou FB-OVF no uso periodico.
  config.fb_count = 1;
  config.grab_mode = CAMERA_GRAB_WHEN_EMPTY;
  config.fb_location = hasPsram ? CAMERA_FB_IN_PSRAM : CAMERA_FB_IN_DRAM;

  esp_err_t error = esp_camera_init(&config);
  if (error != ESP_OK) {
    Serial.printf("Falha ao iniciar camera: 0x%x\n", error);
    return false;
  }

  Serial.printf("PSRAM: %s\n", hasPsram ? "ok" : "nao detectada");
  sensor_t* sensor = esp_camera_sensor_get();
  if (sensor) {
    const char* sensorName = sensor->id.PID == OV5640_PID ? "OV5640" : "outro sensor suportado";
    Serial.printf("Camera: %s (PID: 0x%04x)\n", sensorName, sensor->id.PID);
  }
  Serial.println("Camera inicializada");
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
  if (time(nullptr) < MIN_VALID_EPOCH) {
    clockSynchronized = synchronizeClock();
    if (!clockSynchronized) return;
  }
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

  Serial.printf("JPEG capturado: %u bytes\n", static_cast<unsigned>(frame->len));

  HTTPClient http;
  WiFiClientSecure secure;
  String url = String(API_BASE_URL) + "/api/device/photo/";
  if (!url.startsWith("https://") || strlen(HTTPS_ROOT_CA) < 40) {
    Serial.println("Upload recusado: API_BASE_URL deve usar HTTPS e HTTPS_ROOT_CA deve estar configurada");
    esp_camera_fb_return(frame);
    return;
  }
  secure.setCACert(HTTPS_ROOT_CA);
  Serial.println("Iniciando upload da foto...");
  const bool started = http.begin(secure, url);
  if (!started) {
    Serial.println("Falha ao iniciar conexao HTTPS");
    esp_camera_fb_return(frame);
    return;
  }
  http.setTimeout(15000);
  http.addHeader("Authorization", String("Device ") + DEVICE_API_TOKEN);
  http.addHeader("X-Device-ID", DEVICE_ID);
  http.addHeader("Content-Type", "image/jpeg");
  char capturedAt[32];
  const time_t now = time(nullptr);
  struct tm utcTime;
  gmtime_r(&now, &utcTime);
  strftime(capturedAt, sizeof(capturedAt), "%Y-%m-%dT%H:%M:%SZ", &utcTime);
  http.addHeader("X-Captured-At", capturedAt);
  int status = http.POST(frame->buf, frame->len);
  if (status > 0) {
    Serial.printf("photo: HTTP %d\n", status);
    if (status >= 400) Serial.printf("Resposta: %s\n", http.getString().c_str());
  } else {
    Serial.printf("photo: erro HTTP %d (%s)\n", status, HTTPClient::errorToString(status).c_str());
    char tlsError[160] = {};
    const int tlsCode = secure.lastError(tlsError, sizeof(tlsError));
    Serial.printf("TLS: codigo %d, mensagem: %s\n", tlsCode, tlsError[0] ? tlsError : "indisponivel");
  }
  http.end();
  esp_camera_fb_return(frame);
}
}  // namespace

void setup() {
  Serial.begin(115200);
  Serial.setDebugOutput(true);
  Serial.println("\nHORTA INTELIGENTE - ESP32-CAM");

  if (!startCamera()) return;

  if (!configureWifi()) {
    delay(1000);
    ESP.restart();
  }
  clockSynchronized = synchronizeClock();
}

void loop() {
  processSerialCommand();
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
    WiFi.reconnect();
  }
  if (millis() - lastPhotoUploadAt >= PHOTO_INTERVAL_MS) {
    lastPhotoUploadAt = millis();
    uploadPhoto();
  }
  delay(20);
}
