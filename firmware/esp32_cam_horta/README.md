# ESP32-CAM da Horta

Firmware Arduino para uma placa **AI Thinker ESP32-CAM**, dedicada somente a
imagem. Ele oferece `GET /`, `GET /capture` (JPEG atual) e `GET /stream`
(MJPEG). Sensores, bomba e reles continuam no ESP8266.

## Configurar e gravar

1. Instale no Arduino IDE o pacote **esp32 by Espressif Systems** atualizado.
2. Copie `wifi_config.example.h` para `wifi_config.h` nesta pasta.
3. Preencha o SSID e a senha apenas em `wifi_config.h`; o arquivo e ignorado
   pelo Git.
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
