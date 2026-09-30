# Horta Inteligente

Monólito modular Django para gestão multi-tenant de clientes, assinaturas, hortas,
cultivos, manutenção e dispositivos IoT.

## Desenvolvimento local

Requisitos: Python compatível com a versão declarada em `requirements.txt`.

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
$env:SQLITE_DB_PATH="dev.sqlite3"
.\.venv\Scripts\python manage.py migrate
.\.venv\Scripts\python manage.py createsuperuser
.\.venv\Scripts\python manage.py runserver
```

Sem `DATABASE_URL`, a aplicação usa SQLite. Bancos `*.sqlite3` são locais e não devem
ser versionados.

## Dados de demonstração

Somente em desenvolvimento ou em um ambiente descartável:

```powershell
$env:DEMO_PASSWORD="defina-uma-senha-local-forte"
.\.venv\Scripts\python manage.py seed_demo --show-device-token
```

O comando cria dados fictícios para todas as áreas. A opção explícita acima exibe uma
credencial temporária do simulador somente no terminal local. Sem a opção, o token fica
oculto. A senha demo vem somente de `DEMO_PASSWORD` e não é impressa. Não
execute `seed_demo` automaticamente nem em produção. O valor acima é apenas um
placeholder: escolha outro valor local e nunca o versione.

Usuários criados pelo seed (todos usam a senha fornecida em `DEMO_PASSWORD`):

| Perfil | E-mail |
|---|---|
| Cliente completo | `cliente@hortaviva.local` |
| Técnico | `tecnico@hortaviva.local` |
| Administrador | `admin@hortaviva.local` |
| Cliente sem assinatura | `semassinatura@hortaviva.local` |
| Cliente sem horta | `semhorta@hortaviva.local` |
| Cliente sem dispositivo | `semdispositivo@hortaviva.local` |
| Cliente sem telemetria | `semtelemetria@hortaviva.local` |

O seed é idempotente: pode ser executado novamente para atualizar a demonstração sem
apagar outros clientes. Ele redefine somente as senhas dos usuários demo listados.

```powershell
python scripts\simulate_device.py --token "TOKEN_EMITIDO_PELO_SEED" --once
```

## Variáveis de ambiente

| Variável | Obrigatória em produção | Finalidade |
|---|---:|---|
| `SECRET_KEY` | Sim | Chave secreta do Django |
| `DEBUG` | Sim | Use `False` no Render |
| `DATABASE_URL` | Sim | URL privada do PostgreSQL |
| `ALLOWED_HOSTS` | Recomendada | Hosts adicionais separados por vírgula |
| `CSRF_TRUSTED_ORIGINS` | Recomendada | Origens HTTPS adicionais separadas por vírgula |
| `WEB_CONCURRENCY` | Não | Número de workers Gunicorn; padrão 2 |
| `LOG_LEVEL` | Não | Nível de log em stdout; padrão `INFO` |
| `DEMO_PASSWORD` | Somente demo | Senha dos usuários fictícios do `seed_demo` |
| `RENDER_EXTERNAL_HOSTNAME` | Automática | Host público fornecido pelo Render |
| `SQLITE_DB_PATH` | Apenas local | Caminho opcional do SQLite |

O arquivo `.env.example` contém somente placeholders. Arquivos `.env`, bancos SQLite,
credenciais e tokens nunca devem entrar no Git.

## PostgreSQL

Quando `DATABASE_URL` estiver definida, `dj-database-url` configura o PostgreSQL com
conexões persistentes e verificação de saúde. Sem ela, permanece o SQLite local.

No Render, associe manualmente a **Internal Database URL** do PostgreSQL já existente
à variável `DATABASE_URL` do Web Service. O `render.yaml` não cria outro banco.

## Deploy no Render

O Blueprint está em `render.yaml` e considera o repositório na branch `main`.

Build Command:

```bash
./build.sh
```

O build instala dependências, coleta estáticos e aplica migrations:

```bash
python -m pip install -r requirements.txt
python manage.py collectstatic --noinput
python manage.py migrate --noinput
```

Para este serviço único, executar migrations no build mantém o processo simples. Se a
aplicação passar a ter vários serviços ou deploys concorrentes, mova `migrate` para uma
etapa de pre-deploy controlada pelo Render.

Start Command:

```bash
gunicorn config.wsgi:application
```

O arquivo `gunicorn.conf.py` usa `PORT` e `WEB_CONCURRENCY`, envia logs para stdout e
mantém timeout de 60 segundos.

Health Check Path:

```text
/health/
```

O endpoint retorna apenas `{"status": "ok"}` e não expõe configurações.

### Configuração no painel

1. Crie ou abra o Web Service conectado a `jaquelinedamian/horta-inteligente`.
2. Selecione a branch `main` e runtime Python.
3. Use `./build.sh` como Build Command.
4. Use `gunicorn config.wsgi:application` como Start Command.
5. Configure `/health/` como Health Check Path.
6. Crie `SECRET_KEY` com valor forte gerado fora do repositório.
7. Defina `DEBUG=False`.
8. Associe `DATABASE_URL` à Internal Database URL do PostgreSQL já criado.
9. Defina `ALLOWED_HOSTS` apenas para domínios adicionais. O hostname do Render é
   incluído automaticamente.
10. Defina `CSRF_TRUSTED_ORIGINS` com origens adicionais completas, usando `https://`.
11. Defina `WEB_CONCURRENCY` conforme o plano; 2 é o ponto inicial configurado.

Não coloque valores reais no `render.yaml`, README, commits ou logs.

## Comandos administrativos de produção

Aplicar migrations manualmente, se necessário:

```bash
python manage.py migrate --noinput
```

Criar o primeiro superusuário pelo Shell do Render:

```bash
python manage.py createsuperuser
```

O comando solicita e-mail e senha interativamente; não grave a senha em scripts ou
variáveis versionadas.

## Arquivos estáticos e mídia

WhiteNoise atende CSS e JavaScript coletados em `staticfiles/`. O diretório não é
versionado.

O projeto ainda não possui campos de upload persistente. O filesystem do Web Service
do Render é efêmero; fotos e anexos futuros devem usar object storage, como S3 ou
serviço compatível. Não use `MEDIA_ROOT` local como armazenamento permanente.

## E-mail

O desenvolvimento usa o backend de console. Um provedor SMTP pode ser configurado
posteriormente apenas por variáveis como `EMAIL_HOST`, `EMAIL_HOST_USER`,
`EMAIL_HOST_PASSWORD`, `EMAIL_PORT`, `EMAIL_USE_TLS` e `DEFAULT_FROM_EMAIL`.

## API IoT

## Backoffice operacional

Administradores com `is_staff=True` acessam `/gestao/`. Gestores de organizações,
clientes e técnicos não recebem acesso administrativo automaticamente. O backoffice
oferece listagem, pesquisa, paginação, detalhe, criação e edição para os cadastros
operacionais; telemetria, heartbeats, credenciais e históricos permanecem protegidos
como consulta.

A ação opcional **Criar dados demo** só aparece para superusuários quando estas duas
variáveis estiverem configuradas explicitamente:

```text
ENABLE_DEMO_SEED=True
DEMO_PASSWORD=uma-senha-forte-e-nao-versionada
```

Ela nunca é executada no build, migration ou startup.

## API IoT

Autenticação: `Authorization: Device <prefixo.segredo>`.

- `POST /api/v1/device/telemetry/`
- `POST /api/v1/device/heartbeat/`
- `GET /api/v1/device/commands/`
- `POST /api/v1/device/commands/<uuid>/ack/`

Credenciais de dispositivos são independentes de usuários humanos. Somente o hash do
segredo é persistido. Nunca grave o token emitido em código, documentação ou Git.

O ESP8266/Wemos poderá acessar essas rotas usando o endereço HTTPS do Web Service.

### Firmware do controlador fotografado

O firmware para **Wemos D1 mini (ESP8266) + BMP280 + relé de um canal** está em
[`firmware/esp8266-bmp280-relay`](firmware/esp8266-bmp280-relay/README.md). Ele
envia temperatura e pressão, heartbeat e executa comandos do canal `pump`.
Credenciais de Wi-Fi e o token ficam em um arquivo local ignorado pelo Git.

O BMP280 não mede umidade. Para preencher `air-humidity`, use um BME280 ou outro
sensor compatível; o sistema não deve inferir esse valor.

## Arquitetura IoT

Os dois microcontroladores operam de forma independente, autenticam-se com
`device_id` e token e enviam dados ao Django. O ESP8266 continua responsável
por sensores e automação local; a ESP32-CAM envia fotografias. O Django é a
fonte normal das telas de cliente, técnico e admin.

```text
ESP8266 ---------- telemetria/configuração ---+
                                              +--> Django/PostgreSQL
ESP32-CAM -------- fotografias ---------------+          |
                                                   +------+------+
                                                Cliente Técnico Admin
```

### ESP8266 local

O sketch local esta em
[`firmware/horta_inteligente_local/horta_inteligente_local.ino`](firmware/horta_inteligente_local/horta_inteligente_local.ino).
No Arduino IDE, instale o pacote ESP8266, selecione a placa Wemos/LOLIN D1 mini,
configure os placeholders `WIFI_SSID` e `WIFI_SENHA`, grave e abra o Monitor
Serial em **115200 baud**. O IP sera exibido apos a conexao. Seu endpoint e:

- `GET http://IP_DO_ESP8266/dados` — temperatura, pressao e estados em JSON.

O firmware PlatformIO mais completo, que envia telemetria para a API Django e
controla o rele, permanece documentado em
[`firmware/esp8266-bmp280-relay`](firmware/esp8266-bmp280-relay/README.md).
Nao grave credenciais reais no sketch versionado.

### ESP32-CAM

O firmware e as instrucoes de gravacao estao em
[`firmware/esp32_cam_horta`](firmware/esp32_cam_horta/README.md). No Arduino IDE,
use **AI Thinker ESP32-CAM**, crie `wifi_config.h` a partir do exemplo, grave e
abra o Monitor Serial em **115200 baud**. Endpoints:

- `GET http://IP_DA_CAMERA/` — pagina simples de diagnostico;
- `GET http://IP_DA_CAMERA/capture` — captura JPEG atual;
- `GET http://IP_DA_CAMERA/stream` — stream MJPEG.

O driver oficial atual da Espressif suporta OV2640 e OV5640. A marcacao
`5640-B`, sozinha, nao comprova compatibilidade eletrica/mecanica do modulo com
a placa AI Thinker; consulte a secao OV5640 do README do firmware antes de
trocar a camera.

### IPs locais para diagnóstico

O funcionamento normal não usa IP privado no frontend. O arquivo
[`static/js/device-config.js`](static/js/device-config.js):

```javascript
window.HORTA_DEVICE_CONFIG = Object.freeze({
  ESP8266_BASE_URL: "", // preencha apenas para diagnóstico local
  ESP32_CAM_BASE_URL: "",
  CAMERA_AUTO_REFRESH_MS: 0,
});
```

e os scripts locais permanecem somente para bancada, instalação e diagnóstico;
eles não são carregados pela tela do cliente. `/dados`, `/capture` e `/stream`
continuam úteis na mesma rede durante suporte.

### Limite de acesso local

Essa integracao direta e uma funcionalidade **local**: o navegador precisa
estar na mesma rede e abrir o Django por HTTP local (por exemplo,
`http://localhost:8000`). Uma pagina hospedada em HTTPS, como a do Render,
normalmente nao pode carregar dispositivos `http://192.168.x.x` por bloqueio de
mixed content e politicas de acesso a rede privada. Nao publique os IPs privados
nem abra portas do roteador para contornar isso.

Os firmwares locais enviam CORS para leituras sem credenciais. Como os endpoints
nao possuem autenticacao, use uma rede Wi-Fi confiavel/isolada; o curinga CORS
nao transforma os dispositivos em publicos, mas qualquer pagina acessada por um
cliente dentro dessa rede pode tentar consulta-los.

## Perfis e permissões

- **Cliente:** vê somente hortas das organizações em que possui papel de
  proprietário, gestor ou leitura. Não recebe IP, token ou configuração
  técnica e não edita regras críticas.
- **Técnico:** vê somente hortas em que é técnico principal, possui visita,
  ordem atribuída ou permissão explícita. Usa o checklist de instalação e a
  visão de diagnóstico em campo.
- **Admin:** usuário `is_staff`/superusuário com acesso global ao backoffice,
  culturas, planos, clientes, técnicos, hortas, dispositivos e operações.

O selector `gardens_for_user()` aplica esse escopo no backend. A mesma visão de
status/telemetria/fotografia é reutilizada pelos três perfis e revalida o objeto
por ID; esconder links no HTML não é usado como controle de segurança.

```text
Admin
  +--> Cliente
  +--> Técnico
  +--> Horta
         +--> ESP8266
         +--> ESP32-CAM
```

## Fluxo de instalação

```text
Admin cria instalação e atribui técnico
        ↓
Técnico instala e abre o AP Horta-XXXX
        ↓
Configura Wi-Fi localmente (senha não passa pelo Django)
        ↓
Vincula ESP8266 e ESP32-CAM por device_id/credencial
        ↓
Testa sensores, câmera, bomba e iluminação
        ↓
Confirma cultura/configuração e finaliza checklist
        ↓
Cliente passa a acompanhar a horta
```

Na instalação física, o técnico configura o Wi-Fi **uma única vez**:

```text
Admin cria horta
        ↓
Atribui técnico
        ↓
Técnico liga o equipamento e conecta em Horta-XXXX
        ↓
Seleciona a rede e informa a senha no portal local
        ↓
ESP8266 salva e envia JSON por UART à ESP32-CAM
        ↓
ESP32-CAM persiste no NVS e confirma por ACK
        ↓
Ambos ficam online; técnico testa e finaliza a instalação
        ↓
Cliente passa a acompanhar
```

O ACK da câmera tem timeout: uma câmera ausente nunca bloqueia sensores ou
automação. A identidade `HRT-XXXX-CTRL`/`HRT-XXXX-CAM`, tokens e CA são gravados
na preparação do kit; o técnico apenas vincula o kit no sistema.

Para mudar de residência, mantenha o botão entre D0 e GND pressionado por 5
segundos. O controlador envia `wifi_reset` à câmera, ambos apagam apenas suas
credenciais Wi-Fi e o ESP8266 volta ao AP. A senha nunca passa pelo Django.

O protocolo usa JSON por linha a 9600 baud, com ArduinoJson e mensagens de até
384 bytes. A UART usa D7→GPIO13, GPIO14→D6 e GND comum. Na AI Thinker,
GPIO13/GPIO14 compartilham o barramento do microSD; esta ligação pressupõe que o
slot microSD não será usado.

## APIs atuais dos dispositivos

Autenticação: `Authorization: Device <prefixo.segredo>` e, nas APIs novas,
`X-Device-ID: <serial_number>`. O servidor compara o identificador ao dispositivo
do token. Tokens permanentes nunca devem ser incluídos em QR público.

- `POST /api/device/telemetry/`: payload simplificado do controlador;
- `POST /api/device/photo/`: JPEG da câmera, limitado a 5 MiB por padrão;
- `GET /api/device/config/`: configuração efetiva da cultura mais exceções da horta;
- `/api/v1/device/*`: API anterior de telemetria, heartbeat e comandos, mantida
  para compatibilidade.

Fotografias do MVP são guardadas no banco para não depender do filesystem
efêmero do Render. Para escala maior, migre os binários para object storage.

## Culturas, automação e serviços

`CropCultivationProfile.automation_config` guarda padrões de irrigação,
fertilização e iluminação. `Garden.automation_overrides` contém somente as
exceções daquela horta; a API faz merge recursivo sem alterar o padrão global.
O ESP8266 guarda a última configuração válida no LittleFS e mantém a irrigação
por horário sem internet. No MVP, o fuso embarcado está fixado em UTC-3 para
`America/Sao_Paulo`.

Planos, assinaturas e benefícios existentes formam o catálogo de serviços.
Pedidos avulsos continuam pelo fluxo de chamados/ordens, sem gateway de
pagamento novo. Organização, horta, responsável e atribuições preservam o
isolamento entre clientes e técnicos.

## Checklist antes do push

```powershell
git status
git diff --check
.\.venv\Scripts\python manage.py check
.\.venv\Scripts\python manage.py test
```

Revise cuidadosamente qualquer alteração em arquivos de configuração antes de enviar.
