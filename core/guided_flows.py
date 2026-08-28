"""Presentation metadata for the task-oriented backoffice.

The domain remains in the application modules.  This module only describes how
an operator makes decisions, keeping technical model names out of the journey.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class FlowStep:
    title: str
    description: str
    why: str
    fields: tuple[str, ...]


@dataclass(frozen=True)
class GuidedFlow:
    section: str
    title: str
    intro: str
    icon: str
    steps: tuple[FlowStep, ...]
    success_actions: tuple[tuple[str, str], ...]


def step(title, description, why, fields):
    return FlowStep(title, description, why, tuple(fields.split()))


FLOWS = {
    "plans": GuidedFlow("plans", "Novo plano de assinatura", "Monte a oferta comercial sem precisar criar versões ou benefícios manualmente.", "bi-bag-heart", (
        step("Identidade", "Como este plano será apresentado?", "Estas informações aparecem na página de planos e no checkout.", "name code commercial_title subtitle short_copy description ideal_for image_url"),
        step("Estrutura", "Defina, em linguagem simples, a capacidade oferecida.", "Os limites deixam claro o que o cliente pode usar.", "included_items"),
        step("Preço", "Informe as condições comerciais.", "O sistema cria automaticamente a condição comercial vigente.", "monthly_price installation_fee_cents effective_from"),
        step("Publicação", "Revise onde o plano ficará disponível.", "Planos em rascunho não aparecem para clientes.", "is_public is_featured display_order is_active exclusions"),
    ), (("Ver planos", "plans"), ("Criar cliente", "clients"))),
    "clients": GuidedFlow("clients", "Novo cliente", "Cadastre pessoa, acesso, endereço e assinatura em uma única jornada.", "bi-person-plus", (
        step("Dados", "Quem é o cliente?", "Usamos estes dados para contato e identificação.", "full_name email phone tax_id"),
        step("Acesso", "O cliente poderá entrar na plataforma?", "O acesso permite acompanhar horta, visitas e assinatura.", "password user_is_active"),
        step("Endereço", "Onde a horta poderá ser instalada?", "O endereço será reutilizado na instalação e nas visitas.", "organization_name organization_slug street number city state postal_code"),
        step("Assinatura", "Deseja começar com um plano?", "A assinatura pode ser vinculada agora ou adicionada depois.", "plan_version"),
    ), (("Ver clientes", "clients"), ("Criar horta", "gardens"))),
    "crops": GuidedFlow("crops", "Nova cultura", "Descreva a planta primeiro; necessidades agronômicas ficam organizadas e explicadas.", "bi-flower2", (
        step("Identificação", "Qual planta será cultivada?", "Estas informações identificam a cultura no catálogo.", "common_name scientific_name code category description image_url uses"),
        step("Necessidades", "Do que esta planta precisa?", "As faixas orientam cultivo, automação e alertas.", "minimum_temperature ideal_temperature_min ideal_temperature_max maximum_temperature minimum_humidity maximum_humidity light_hours minimum_pot_liters"),
        step("Ciclo", "Como é o ciclo desta planta?", "A estimativa ajuda a planejar trocas e colheitas.", "life_cycle allows_regrowth estimated_harvests cut_interval_days difficulty light_requirement"),
        step("Publicação", "Disponibilizar esta cultura?", "Quando ativa, ela aparece no catálogo e pode ser escolhida pelos clientes; variedades continuam opcionais.", "is_available is_featured page_title short_description flavor aroma botanical_family origin edible_part"),
    ), (("Ver culturas", "crops"), ("Adicionar variedade", "cultivars"))),
    "gardens": GuidedFlow("gardens", "Nova horta", "Associe cliente, local e configuração do equipamento.", "bi-house-heart", (
        step("Cliente", "Para quem é esta horta?", "A horta precisa pertencer ao cliente correto.", "organization subscription name code"),
        step("Local", "Onde será instalada?", "O local orienta instalação e atendimento técnico.", "address location_name position_description timezone responsible sunlight socket_nearby wifi_available wifi_quality pets children restrictions site_notes"),
        step("Configuração", "Qual é a estrutura da horta?", "Capacidade e equipamentos guiam módulos e manutenção.", "equipment_model module_capacity reservoir_liters grow_light_type pump_model controller_model"),
        step("Instalação", "Defina situação e responsável.", "O status correto organiza o próximo trabalho da equipe.", "status technical_status primary_technician installed_at operational_notes is_active"),
    ), (("Ver hortas", "gardens"), ("Criar módulo", "modules"))),
    "modules": GuidedFlow("modules", "Novo módulo", "Cadastre o módulo físico e deixe a instalação para o momento certo.", "bi-box", (
        step("Tipo", "Que tipo de módulo é este?", "O tipo reúne capacidade e recursos técnicos.", "module_type"),
        step("Identificação", "Como a equipe reconhecerá o módulo?", "Serial e código evitam trocas durante instalação e suporte.", "organization serial_number name qr_identifier"),
        step("Situação", "Onde este módulo ficará agora?", "Um módulo só fica instalado quando está vinculado a uma horta.", "placement garden installation_position installation_date position_label pot_volume_liters substrate_capacity_liters notes"),
    ), (("Ver módulos", "modules"), ("Gerar QR Code", "qrcodes"))),
    "employees": GuidedFlow("employees", "Novo funcionário", "Cadastre a pessoa e defina seu acesso de trabalho.", "bi-person-badge", (
        step("Dados pessoais", "Quem fará parte da equipe?", "Nome e contato identificam a pessoa na agenda e nas ordens.", "full_name email phone"),
        step("Acesso", "Como essa pessoa usará a plataforma?", "Acesso de gestão é diferente de estar com o cadastro ativo.", "password is_staff is_active"),
    ), (("Ver equipe", "employees"), ("Agendar visita", "visits"))),
    "inventory": GuidedFlow("inventory", "Novo insumo", "Cadastre o item e escolha somente os controles de estoque necessários.", "bi-box-seam", (
        step("Identificação", "Que item é este?", "SKU, nome e categoria facilitam busca e reposição.", "sku name inventory_category description"),
        step("Fornecimento", "De quem compramos este item?", "Marca e fornecedor apoiam compras e rastreabilidade.", "primary_supplier brand unit"),
        step("Controle", "Você precisa controlar lote ou validade?", "Ative apenas os controles relevantes para este item.", "tracks_lots tracks_expiration minimum_quantity reorder_point physical_location"),
        step("Valores", "Quais são os valores de referência?", "Custos apoiam estoque e operação, sem alterar movimentações.", "average_cost_cents reference_price_cents is_active"),
    ), (("Ver estoque", "inventory"), ("Registrar entrada", "stock-movements"))),
    "devices": GuidedFlow("devices", "Novo dispositivo", "Identifique o equipamento e associe-o ao local de uso.", "bi-cpu", (
        step("Modelo", "Qual é o modelo do dispositivo?", "O modelo reúne capacidades e especificações de hardware.", "model"),
        step("Identificação", "Como este equipamento será reconhecido?", "Nome e serial são usados no suporte e na telemetria.", "name serial_number firmware_version"),
        step("Uso", "Onde será utilizado?", "A associação correta filtra módulos, leituras e comandos.", "organization module status"),
        step("Avançado", "Há metadados técnicos adicionais?", "Use somente quando a implantação exigir configuração específica.", "metadata"),
    ), (("Ver dispositivos", "devices"), ("Configurar sensores", "channels"))),
    "visits": GuidedFlow("visits", "Nova visita", "Agende o atendimento no contexto do cliente e da horta.", "bi-calendar2-check", (
        step("Motivo", "Por que a equipe fará esta visita?", "O motivo prepara checklist e tempo de atendimento.", "visit_type reason"),
        step("Cliente e horta", "Onde será o atendimento?", "Ao escolher o cliente, use apenas uma horta pertencente a ele.", "organization garden work_order"),
        step("Técnico", "Quem realizará o atendimento?", "A visita aparecerá na agenda dessa pessoa.", "technician"),
        step("Data", "Quando acontecerá?", "Horário e duração organizam a agenda operacional.", "scheduled_start scheduled_end status notes"),
    ), (("Ver agenda", "visits"), ("Criar ordem", "orders"))),
    "orders": GuidedFlow("orders", "Nova ordem de serviço", "Transforme uma necessidade operacional em trabalho acompanhado.", "bi-clipboard-check", (
        step("Contexto", "Para quem e onde será o serviço?", "O contexto conecta histórico de cliente, horta e equipamento.", "organization garden module device"),
        step("Serviço", "O que precisa ser feito?", "Título, tipo e descrição orientam a execução.", "kind title description maintenance_plan"),
        step("Prioridade", "Quando e com qual urgência?", "Prioridade e data ajudam a equipe a ordenar o trabalho.", "priority scheduled_for status"),
    ), (("Ver ordens", "orders"), ("Agendar visita", "visits"))),
}


PRIMARY_ACTIONS = tuple(FLOWS.values())


def get_flow(section):
    return FLOWS.get(section)
