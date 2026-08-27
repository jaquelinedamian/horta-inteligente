# Fluxos guiados do backoffice

Os fluxos abaixo são a camada principal de experiência. Os CRUDs continuam em **Configurações avançadas** para manutenção técnica. Nenhum model novo foi criado.

| Ação | Passos visíveis | Models usados | Resultado |
| --- | --- | --- | --- |
| Novo plano | Identidade → Estrutura → Preço → Publicação | `Plan`, `PlanVersion`, `PlanEntitlement` | Oferta comercial publicável e utilizável no checkout |
| Novo cliente | Dados → Acesso → Endereço → Assinatura | `User`, `Organization`, `Membership`, `Address`, `Subscription` | Cliente com acesso e assinatura opcional |
| Nova cultura | Identificação → Necessidades → Ciclo → Publicação | `Crop` (detalhes técnicos seguem disponíveis na central da cultura) | Cultura disponível para catálogo e cultivo |
| Nova horta | Cliente → Local → Configuração → Instalação | `Garden`, relações existentes com `Organization`, `Address` e `Subscription` | Horta preparada para módulos e instalação |
| Novo módulo | Tipo → Identificação → Situação | `GardenModule`, `ModuleType` | Módulo físico rastreável; instalação é feita quando houver destino |
| Novo funcionário | Dados pessoais → Acesso | `User` | Integrante ativo na equipe; vínculo técnico permanece no domínio existente |
| Novo insumo | Identificação → Fornecimento → Controle → Valores | `InventoryItem`, `InventoryCategory`, `Supplier` | Item preparado para entradas via `StockMovement` |
| Novo dispositivo | Modelo → Identificação → Uso → Avançado | `Device`, `DeviceModel` | Dispositivo pronto para credencial e canais |
| Nova visita | Motivo → Cliente e horta → Técnico → Data | `Visit`, relações com `Organization`, `Garden`, `User`, `WorkOrder` | Atendimento visível na agenda do técnico |
| Nova ordem | Contexto → Serviço → Prioridade | `WorkOrder` e relações operacionais | Trabalho acompanhado pela operação |

## Decisões arquiteturais

- A interface chama serviços transacionais em `core/workflow_services.py`.
- `CommercialPlanForm` continua criando versão vigente e itens incluídos automaticamente.
- `ClientOnboardingForm` continua criando pessoa, organização, vínculo, endereço e assinatura em uma transação.
- Rascunhos ficam no navegador e não criam registros incompletos no banco.
- Relacionamentos auxiliares continuam acessíveis dentro do fluxo e em Configurações avançadas.
- Não houve migration: a simplificação é de experiência e orquestração, não de domínio.
