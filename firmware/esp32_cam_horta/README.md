# ESP32-CAM da Horta

Firmware Arduino para uma placa **AI Thinker ESP32-CAM**, dedicada somente a
imagem. Ele oferece `GET /`, `GET /capture` (JPEG atual) e `GET /stream`
(MJPEG). Sensores, bomba e reles continuam no ESP8266.

## Configurar e gravar

1. Instale no Arduino IDE o pacote **esp32 by Espressif Systems** atualizado e
   a biblioteca **ArduinoJson 7**.
2. Copie `wifi_config.example.h` para `wifi_config.h` nesta pasta.
3. Preencha somente a identidade pre-provisionada do kit, a URL HTTPS, token e
   CA raiz em `wifi_config.h`; o arquivo e ignorado pelo Git. SSID e senha não
   ficam nesse arquivo.
4. Abra `esp32_cam_horta.ino` e selecione **AI Thinker ESP32-CAM**.
5. Para gravar com adaptador USB/serial, alimente a placa adequadamente, cruze
   TX/RX, una GPIO 0 ao GND durante o upload e reinicie a placa. Remova a uniao
   GPIO 0/GND e reinicie depois da gravacao.
6. Abra o Monitor Serial em **115200 baud** e copie o IP exibido.

O sketch usa a pinagem `CAMERA_MODEL_AI_THINKER` publicada no exemplo oficial
CameraWebServer da Espressif, isolada em `camera_pins.h`. Nao altere essa
pinagem com base apenas no nome impresso no sensor.

## OV5640 / modulo marcado 5640-B

O driver `esp32-camera` atual da Espressif declara suporte a OV5640 e detecta o
modelo em tempo de execucao; o PID detectado e impresso no Serial. Isso nao
garante que qualquer modulo OV5640 seja substituto fisico do OV2640 da placa AI
Thinker. O flat cable precisa ter pinout, quantidade de vias, tensoes e interface
DVP compativeis com a placa. Se a inicializacao falhar, nao adapte GPIOs por
tentativa: confirme primeiro a documentacao exata do modulo e do fornecedor.

Foi escolhida resolucao SVGA com PSRAM (VGA sem PSRAM), conservadora para
captura e streaming. Autofoco de alguns OV5640 exige suporte/configuracao
adicional do driver e nao e necessario para os endpoints deste MVP.

## Rede e seguranca

As respostas incluem CORS para leitura `GET` sem credenciais pelo dashboard em
outra origem local. O servidor nao possui autenticacao; mantenha-o em uma rede
Wi-Fi confiavel/isolada e nao encaminhe a porta 80 no roteador. O firmware usa
HTTP local, nao HTTPS.

No fluxo normal, a câmera envia um JPEG periodicamente para
`POST /api/device/photo/`. Os endpoints `/capture` e `/stream` continuam apenas
para diagnóstico local. O token identifica a câmera e nunca deve aparecer em QR
público, HTML ou logs.

## Provisionamento único pela UART

A câmera abre o NVS com `Preferences`. Se houver SSID salvo, tenta conectar. Se
não houver, continua operacional localmente e aguarda uma linha JSON enviada
pelo ESP8266 a 9600 baud:

```json
{"type":"wifi_config","ssid":"MinhaRede","password":"MinhaSenha"}
```

ArduinoJson faz o escaping de caracteres especiais. A mensagem tem limite de
384 bytes e termina em newline. Depois de validar os limites do Wi-Fi, a câmera
salva as credenciais no namespace `horta-wifi`, responde
`{"type":"wifi_ack","status":"ok"}` e reinicia. A senha nunca é impressa.

O reset chega como `{"type":"wifi_reset"}`. A câmera apaga o namespace,
responde `wifi_reset_ack` e reinicia aguardando novo provisionamento.

### Ligação UART

Esta ligação é válida para AI Thinker **sem uso do slot microSD**:

| Wemos D1 mini | ESP32-CAM AI Thinker | Função |
|---|---|---|
| D7 / GPIO13 (TX) | GPIO13 (RX2) | ESP8266 → câmera |
| D6 / GPIO12 (RX) | GPIO14 (TX2) | câmera → ESP8266 |
| GND | GND | referência comum |

GPIO13 e GPIO14 da AI Thinker não são usados pela câmera nem são pinos de boot,
mas pertencem ao barramento do microSD. Não instale cartão microSD com essa
UART. Ambos os lados trabalham em 3,3 V; não aplique 5 V nos sinais.
