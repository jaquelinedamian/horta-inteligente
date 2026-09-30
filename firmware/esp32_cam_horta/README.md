# ESP32-CAM da Horta

Firmware Arduino para uma placa **AI Thinker ESP32-CAM**, dedicada somente a
imagem. Ele oferece `GET /`, `GET /capture` (JPEG atual) e `GET /stream`
(MJPEG). Sensores, bomba e reles continuam no ESP8266.

## Configurar e gravar

1. Instale no Arduino IDE o pacote **esp32 by Espressif Systems** atualizado e
   a biblioteca **WiFiManager 2.0.17 ou compatível**.
2. Copie `wifi_config.example.h` para `wifi_config.h` nesta pasta.
3. Preencha somente a identidade pre-provisionada do kit, a URL HTTPS, token e
   CA raiz em `wifi_config.h`; o arquivo e ignorado pelo Git. SSID e senha não
   ficam nesse arquivo.
4. Abra `esp32_cam_horta.ino` e selecione **AI Thinker ESP32-CAM**.
5. Para gravar com adaptador USB/serial, alimente a placa adequadamente, cruze
   TX/RX, una GPIO 0 ao GND durante o upload e reinicie a placa. Remova a uniao
   GPIO 0/GND e reinicie depois da gravacao.
6. Abra o Monitor Serial em **115200 baud** e copie o IP exibido.

Como alternativa reproduzível, instale PlatformIO e execute `pio run` nesta
pasta. O ambiente `esp32cam` e a dependência do WiFiManager estão declarados em
`platformio.ini`.

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

## Provisionamento Wi-Fi independente

Depois de iniciar a câmera, o WiFiManager tenta as credenciais salvas pela
própria ESP32-CAM. Sem conexão, abre o AP `Horta-Camera-<chip-id>` e o portal em
`192.168.4.1`. O técnico seleciona a rede da residência e informa a senha no
próprio dispositivo; a senha fica na NVS da ESP32 e nunca é enviada ao Django
ou ao ESP8266. Nos próximos boots, a câmera reconecta automaticamente.

A câmera não possui UART de provisionamento e não depende do controlador. Sua
identidade, token e CA ficam no `wifi_config.h` local ignorado pelo Git; esse
arquivo não contém SSID nem senha.

## Reset do Wi-Fi

Nenhum botão físico foi atribuído: a pinagem da câmera AI Thinker foi preservada
e GPIO4 pode ser usado pelo flash/slot SD. Com um adaptador serial conectado,
abra o monitor em 115200 baud, envie `RESET_WIFI` seguido de Enter e aguarde o
AP próprio. Como alternativa de manutenção, apague a flash e grave novamente.
Ambos os procedimentos afetam somente a câmera.

## HTTPS_ROOT_CA

O upload HTTPS é recusado quando a CA está vazia. Obtenha a cadeia TLS do
domínio Render real por navegador ou OpenSSL, valide emissor e validade e copie
o PEM da CA raiz para `HTTPS_ROOT_CA`. O firmware usa `setCACert()` e nunca
desativa a validação TLS. Não há uma CA aleatória hardcodada porque a cadeia do
serviço pode mudar.
