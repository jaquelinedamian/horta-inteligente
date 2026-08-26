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

Autenticação: `Authorization: Device <prefixo.segredo>`.

- `POST /api/v1/device/telemetry/`
- `POST /api/v1/device/heartbeat/`
- `GET /api/v1/device/commands/`
- `POST /api/v1/device/commands/<uuid>/ack/`

Credenciais de dispositivos são independentes de usuários humanos. Somente o hash do
segredo é persistido. Nunca grave o token emitido em código, documentação ou Git.

O ESP8266/Wemos poderá acessar essas rotas usando o endereço HTTPS do Web Service.

## Checklist antes do push

```powershell
git status
git diff --check
.\.venv\Scripts\python manage.py check
.\.venv\Scripts\python manage.py test
```

Revise cuidadosamente qualquer alteração em arquivos de configuração antes de enviar.
