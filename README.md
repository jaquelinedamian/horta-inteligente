# Horta Inteligente

Monólito modular Django para gestão multi-tenant de clientes, assinaturas, hortas,
módulos, cultivos, manutenção e dispositivos IoT.

## Desenvolvimento

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\python manage.py migrate
.\.venv\Scripts\python manage.py createsuperuser
.\.venv\Scripts\python manage.py runserver
```

O SQLite é usado quando `POSTGRES_DB` não está definido. Para ambientes persistentes,
configure as variáveis de PostgreSQL mostradas em `.env.example`.

> O `db.sqlite3` que acompanhava o esqueleto possui apenas migrations nativas já
> aplicadas. Como esta implementação introduz `AUTH_USER_MODEL`, inicie um banco novo
> (ou faça backup e uma migração de dados planejada) antes de executar `migrate`.

## Ambiente demonstrativo e simulador

```powershell
.\.venv\Scripts\python manage.py seed_demo
python scripts\simulate_device.py --token "TOKEN_EXIBIDO_PELO_SEED" --once
```

Depois, execute `runserver` e abra `http://127.0.0.1:8000/`. A demonstração cria:

- cliente: `cliente@hortaviva.local` / `demo1234`;
- técnico: `tecnico@hortaviva.local` / `demo1234`;
- operação: `admin@hortaviva.local` / `demo1234`.

As áreas ficam em `/app/`, `/operacao/` e `/gestao/`. O admin técnico nativo
continua disponível em `/admin/`.

O seed cria um Wemos D1 Mini/ESP8266 com canais genéricos correspondentes ao BME280,
FD10, relé de bomba e relé de grow light. O token é exibido uma única vez; somente seu
hash é persistido.

Para materializar a programação de luz em comandos, execute a cada minuto (via cron,
serviço do sistema ou worker futuro):

```powershell
.\.venv\Scripts\python manage.py run_lighting_scheduler
```

## API do dispositivo

Autenticação em todas as rotas: `Authorization: Device <prefixo.segredo>`.

- `POST /api/v1/device/telemetry/`
- `POST /api/v1/device/heartbeat/`
- `GET /api/v1/device/commands/`
- `POST /api/v1/device/commands/<uuid>/ack/`

Cada leitura e comando possui chave de idempotência. Credenciais de dispositivo são
independentes de usuários humanos e podem ser rotacionadas ou revogadas.
