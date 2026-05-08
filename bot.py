import discord
from discord import app_commands
from discord.ext import commands
import psycopg2
import time
import datetime
import os
import io
from dotenv import load_dotenv
from typing import Optional
import requests
from bs4 import BeautifulSoup
from discord.ext import tasks

load_dotenv()
TOKEN = os.getenv('TOKEN')

# Configuração do Banco de Dados
DATABASE_URL = os.getenv('DATABASE_URL')

def get_connection():
    return psycopg2.connect(DATABASE_URL, sslmode='require')

# Inicialização das tabelas
def init_db():
    conn = get_connection()
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS reputacao (
            user_id BIGINT PRIMARY KEY,
            pontos INTEGER DEFAULT 0
        )
    ''')
    conn.commit()
    cur.close()
    conn.close()

init_db()

@tasks.loop(minutes=10)
async def monitorar_condicoes_mapa():
    canal_id = 1433136439456956576  # ID do seu canal
    canal = bot.get_channel(canal_id)
    if not canal:
        return

    url = "https://arcraiders.com/pt-BR/map-conditions"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    try:
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code != 200:
            return

        soup = BeautifulSoup(response.text, 'html.parser')
        
        embed = discord.Embed(
            title="🌍 CONDIÇÕES DOS MAPAS - ARC RAIDERS",
            url=url,
            description="Relatório de inteligência sobre anomalias e eventos.",
            color=0xf1c40f,
            timestamp=datetime.datetime.now()
        )

        # 1. BUSCAR EVENTOS ATIVOS (Active Now)
        # O site costuma usar classes como 'active' ou 'current' para o que está rolando agora
        ativos = soup.find_all(class_=lambda x: x and 'active' in x.lower())
        if ativos:
            lista_ativos = ""
            for item in ativos[:3]: # Pega os 3 primeiros
                txt = item.get_text(strip=True)
                if txt: lista_ativos += f"🔴 **{txt}**\n"
            
            if lista_ativos:
                embed.add_field(name="🔥 ATIVO AGORA", value=lista_ativos, inline=False)

        # 2. BUSCAR PRÓXIMOS EVENTOS (Coming Up)
        # O site costuma usar 'coming' ou 'next' para os futuros
        proximos = soup.find_all(class_=lambda x: x and 'coming' in x.lower())
        if proximos:
            lista_proximos = ""
            for item in proximos[:3]:
                txt = item.get_text(strip=True)
                if txt: lista_proximos += f"⏳ *{txt}*\n"
            
            if lista_proximos:
                embed.add_field(name="📅 EM BREVE", value=lista_proximos, inline=False)

        # Caso a raspagem por classe falhe (site dinâmico), mantém um aviso
        if not embed.fields:
            embed.description = "🛰️ **Sinal instável.** Verifique o status detalhado no [Site Oficial](https://arcraiders.com/pt-BR/map-conditions)."

        embed.set_footer(text="Atualização automática | Fonte: arcraiders.com")

        # 3. LIMPEZA E ENVIO
        async for mensagem in canal.history(limit=15):
            if mensagem.author == bot.user and mensagem.embeds:
                if "CONDIÇÕES DOS MAPAS" in mensagem.embeds[0].title:
                    try:
                        await mensagem.delete()
                    except:
                        pass

        await canal.send(embed=embed)

    except Exception as e:
        print(f"Erro ao monitorar site: {e}")

class ARC_Bot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.all() # Necessário para gerenciar cargos e canais
        super().__init__(command_prefix="/", intents=intents)

async def setup_hook(self):
        # Limpa o cache de comandos para evitar conflitos de nomes duplicados ou antigos
        # self.tree.clear_commands(guild=None) # Opcional: use se o erro persistir

        self.add_view(RegrasView())
        self.add_view(SuporteView())
        self.add_view(TicketActionView())

        # Sincroniza novamente
        await self.tree.sync()
        print("✅ Comandos de barra sincronizados com sucesso!")

bot = ARC_Bot()

@bot.event
async def on_ready():
    print(f'🤖 {bot.user.name} online e monitorando o mapa!')
    if not monitorar_condicoes_mapa.is_running():
        monitorar_condicoes_mapa.start()

# --- UTILS REPUTAÇÃO ---

def update_rep(user_id, valor):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute('''
        INSERT INTO reputacao (user_id, pontos) VALUES (%s, %s)
        ON CONFLICT (user_id) DO UPDATE SET pontos = reputacao.pontos + %s
        RETURNING pontos
    ''', (user_id, valor, valor))
    novo_total = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    return novo_total

async def check_roles(member, pontos):
    # Cargos em letras minúsculas conforme solicitado
    roles_map = {
        "trocador oficial 💎": pontos >= 100,
        "trocador confiável ✅": 50 <= pontos < 100,
        "trocador iniciante ✅": 10 <= pontos < 50,
        "trocador perigoso ❌": pontos <= -10,
        "neutro": -9 <= pontos < 10
    }
    
    for role_name, condition in roles_map.items():
        role = discord.utils.get(member.guild.roles, name=role_name)
        if role:
            if condition:
                await member.add_roles(role)
            else:
                await member.remove_roles(role)

# --- VIEWS E MODALS ---

class RegrasView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Concordar e Aceitar Regras", style=discord.ButtonStyle.green, custom_id="regras_aceitar")
    async def concordar(self, interaction: discord.Interaction, button: discord.ui.Button):
        role = discord.utils.get(interaction.guild.roles, name="speranza")
        if role:
            await interaction.user.add_roles(role)
            await interaction.response.send_message("Você concordou com as regras e recebeu o cargo `speranza`!", ephemeral=True)

class CloseTicketModal(discord.ui.Modal, title="Encerrar Atendimento"):
    motivo = discord.ui.TextInput(label="Motivo do fechamento", style=discord.TextStyle.paragraph, placeholder="Explique o motivo...")

    async def on_submit(self, interaction: discord.Interaction):
        log_channel = bot.get_channel(1433136439456956576)
        
        # Gerar Log TXT
        history = []
        async for msg in interaction.channel.history(limit=None, oldest_first=True):
            history.append(f"[{msg.created_at.strftime('%d/%m/%Y %H:%M')}] {msg.author.name}: {msg.content}")
        
        file_data = "\n".join(history)
        file = discord.File(io.BytesIO(file_data.encode()), filename=f"log-ticket-{interaction.channel.name}.txt")
        
        await log_channel.send(f"📌 **Ticket Encerrado**\n**Canal:** {interaction.channel.name}\n**Fechado por:** {interaction.user.mention}\n**Motivo:** {self.motivo.value}", file=file)
        await interaction.response.send_message("O ticket será excluído em instantes...")
        await interaction.channel.delete()

class TicketActionView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Encerrar Atendimento", style=discord.ButtonStyle.red, custom_id="btn_close_ticket")
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        is_mod = any(role.name.lower() == "mods" for role in interaction.user.roles)
        if not is_mod:
            return await interaction.response.send_message("Apenas membros com o cargo `mods` podem fechar tickets.", ephemeral=True)
        await interaction.response.send_modal(CloseTicketModal())

class SuporteView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Abrir Ticket", style=discord.ButtonStyle.primary, custom_id="btn_open_ticket")
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        cat_id = 1432701386738499666
        category = interaction.guild.get_channel(cat_id)
        
        overwrites = {
            interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True),
            discord.utils.get(interaction.guild.roles, name="mods"): discord.PermissionOverwrite(view_channel=True)
        }
        
        channel = await interaction.guild.create_text_channel(f"ticket-{interaction.user.name}", category=category, overwrites=overwrites)
        
        embed = discord.Embed(
            title="🛰️ Central de Suporte - ARC Raiders Brasil",
            description=(
                f"Olá {interaction.user.mention}, favor ler abaixo e explicar a sua situação.\n\n"
                "*Caso tenha aberto o ticket por engano favor informar.* \n"
                "*Para denúncias:* Informar o ocorrido, enviar prints/vídeos e o ID (discord) do suspeito. \n"
                "*Para bugs/suporte ao jogo: Logue com sua Embark ID e abra um ticket no link:* https://id.embark.games/pt-BR/arc-raiders/support \n\n"
                "Para as denúncias, as medidas serão tomadas apenas caso tenha provas consistentes e concretas sobre o assunto abordado. \n"
                "Aguarde um membro da staff entrar em contato."
            ),
            color=0x3498db
        )
        embed.set_footer(text="Use o botão abaixo para encerrar o atendimento.")
        await channel.send(embed=embed, view=TicketActionView())
        await interaction.response.send_message(f"Ticket aberto em {channel.mention}", ephemeral=True)

class RaidView(discord.ui.View):
    def __init__(self, autor, vagas_totais, mapa, objetivo, cat_id, limit):
        super().__init__(timeout=3600)
        self.autor = autor
        self.vagas_totais = vagas_totais
        self.participantes = [autor]
        self.mapa = mapa
        self.objetivo = objetivo
        self.cat_id = cat_id
        self.limit = limit

    def gerar_embed(self, encerrado=False):
        restantes = self.vagas_totais - len(self.participantes)
        lista_membros = "\n".join([f"• {p.mention}" for p in self.participantes])
        
        cor = 0x2ecc71 if encerrado else 0xe67e22
        titulo = "✅ SQUAD FORMADO" if encerrado else "🚨 RECRUTAMENTO DE RAID"

        embed = discord.Embed(title=titulo, color=cor)
        embed.add_field(name="Informações", value=f"**Mapa:** `{self.mapa}`\n**Objetivo:** `{self.objetivo}`\n**Tipo:** `{'DUO' if self.limit == 2 else 'TRIO'}`", inline=False)
        embed.add_field(name=f"Operadores ({len(self.participantes)}/{self.vagas_totais})", value=lista_membros, inline=False)
        
        if not encerrado:
            embed.set_footer(text=f"Aguardando mais {restantes} raider(s)...")
        else:
            embed.set_footer(text=f"Aguardando {self.autor.name} iniciar o canal de voz.")
        return embed

    @discord.ui.button(label="Participar", style=discord.ButtonStyle.green, emoji="🔫", custom_id="btn_participar")
    async def participar(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id in [p.id for p in self.participantes]:
            return await interaction.response.send_message("Você já está neste squad!", ephemeral=True)
        
        self.participantes.append(interaction.user)

        if len(self.participantes) >= self.vagas_totais:
            # Desabilita o botão participar e limpa a view para adicionar o botão do líder
            self.clear_items()
            btn_gerar = discord.ui.Button(label="Criar Canal de Voz", style=discord.ButtonStyle.primary, emoji="🔊")
            
            async def gerar_callback(inter: discord.Interaction):
                if inter.user.id != self.autor.id:
                    return await inter.response.send_message("Apenas o líder do squad pode iniciar o canal.", ephemeral=True)
                
                guild = inter.guild
                category = guild.get_channel(self.cat_id)
                prefixo = "Duo" if self.limit == 2 else "Trio"
                
                new_channel = await guild.create_voice_channel(
                    name=f"{prefixo}: {self.autor.name}",
                    category=category,
                    user_limit=self.limit
                )
                
                await inter.response.send_message(f"✅ Canal {new_channel.mention} criado com sucesso!", ephemeral=True)
                # Remove o botão após criar o canal
                self.clear_items()
                await inter.edit_original_response(view=self)
                self.stop()

            btn_gerar.callback = gerar_callback
            self.add_item(btn_gerar)
            
            mencoes = " ".join([p.mention for p in self.participantes])
            await interaction.response.edit_message(content=f"🚀 {mencoes} **O SQUAD ESTÁ PRONTO!**", embed=self.gerar_embed(encerrado=True), view=self)
        else:
            await interaction.response.edit_message(embed=self.gerar_embed(), view=self)

# --- COMANDOS ---

@bot.tree.command(name="ajuda", description="Exibe o terminal de suporte")
async def ajuda(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🛰️ TERMINAL DE SUPORTE - ARC RAIDERS BRASIL",
        description="Bem-vindo ao sistema de auxílio automatizado.\n\n**PS:** Comandos de troca funcionam apenas no canal de trocas.",
        color=0x3498db
    )
    embed.add_field(name="📦 SISTEMA DE TROCAS", value="🌟 `/rep membro` - Dá +1 de reputação positiva.\n💢 `/neg membro` - Dá -1 de reputação negativa.\n👤 `/perfil membro` - Consulta a ficha do raider.\n🏆 `/top` - Ranking dos mais confiáveis.", inline=False)
    
    is_mod = any(role.name.lower() == "mods" for role in interaction.user.roles)
    is_admin = interaction.user.guild_permissions.administrator

    if is_mod or is_admin:
        embed.add_field(name="🛠️ PROTOCOLOS DE COMANDO (STAFF)", value="📢 `/falar texto` - Anúncios oficiais.\n🧹 `/limpar quantidade` - Limpa mensagens.\n📜 `/setrep membro pontos` - Ajusta reputação.\n⚙️ `/status` - Status do bot.", inline=False)

    if interaction.guild.icon:
        embed.set_thumbnail(url=interaction.guild.icon.url)
    
    embed.set_footer(text=f"Developer: {interaction.user.name} | Sponsors: !Gio, WARCELUS, lari nunes", icon_url=interaction.user.display_avatar.url)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="postar_regras", description="Posta o sistema de regras oficial do servidor")
async def postar_regras(interaction: discord.Interaction):
    # Verificação de segurança para apenas administradores
    if not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("Apenas administradores podem executar este protocolo.", ephemeral=True)

    embed = discord.Embed(
        title="🛰️ DIRETRIZES DA COMUNIDADE - ARC RAIDERS BRASIL",
        description=(
            "Bem-vindo à Resistência! Para garantir uma convivência tática e justa, siga as normas:\n\n"
            "🤝 **1. RESPEITO ACIMA DE TUDO**\n"
            "Sem toxicidade, racismo, homofobia ou qualquer tipo de preconceito. Somos uma comunidade.\n\n"
            "🚫 **2. PROIBIDO RMT (Real Money Trade)**\n"
            "Compra e venda de itens ou contas por dinheiro real é terminantemente proibida. Sujeito a banimento imediato.\n\n"
            "🛡️ **3. TRAPAÇAS E HACKS**\n"
            "O uso de softwares de terceiros (Aimbot, Wallhack, etc) resultará em blacklist global no servidor e denúncia para os devs. Inclui mencionar o uso ou compartilhar links desses conteúdos.\n\n"
            "📦 **4. CANAIS DE TROCA**\n"
            "Use o sistema de reputação (`/rep` e `/neg`) para manter a segurança da comunidade.\n\n"
            "🏃 **5. CONDUTA EM RAID**\n"
            "Seja um bom parceiro. Abandonar o squad propositalmente ou 'trollar' extrações gera má reputação.\n\n"
            "📢 **6. SEM PUBLICIDADE**\n"
            "Não é permitido publicar links, convites ou promoção em redes sociais sem autorização.\n\n"
            "⚖️ **7. SEM DISCUSSÕES POLARIZADAS**\n"
            "Evite tópicos como política ou religião com a intenção de causar conflito ou indignação.\n\n"
            "--- \n"
            "**Segurança ARC Raiders Brasil** • *O bom senso é a regra principal.*"
        ),
        color=0x3498db
    )
    
    if interaction.guild.icon:
        embed.set_thumbnail(url=interaction.guild.icon.url)

    embed.set_footer(text="Ao clicar no botão abaixo, você declara estar ciente e de acordo.")

    # Envia o embed com a View que já contém o botão para o cargo 'speranza'
    await interaction.channel.send(embed=embed, view=RegrasView())
    await interaction.response.send_message("✅ Protocolo de Regras postado com sucesso.", ephemeral=True)

@bot.tree.command(name="postar_suporte", description="Posta o sistema de tickets")
async def postar_suporte(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator: return
    embed = discord.Embed(
        title="📩 Precisa de ajuda ou denunciar algo?",
        description=(
            "Clique no botão abaixo para abrir um canal de atendimento privado com a staff.\n\n"
            "**O que você pode tratar aqui:**\n"
            "• Denúncias de hackers/scammers\n"
            "• Quebra de regras\n"
            "• Dúvidas gerais\n\n"
            "*Evite abrir tickets sem necessidade.*"
        ),
        color=0x3498db
    )
    await interaction.channel.send(embed=embed, view=SuporteView())
    await interaction.response.send_message("Mensagem de suporte enviada.", ephemeral=True)

@bot.tree.command(name="rep")
@app_commands.checks.cooldown(1, 3600, key=lambda i: i.user.id)
async def rep(interaction: discord.Interaction, membro: discord.Member):
    if membro.id == interaction.user.id:
        return await interaction.response.send_message("Você não pode dar reputação para si mesmo.", ephemeral=True)
    
    pontos = update_rep(membro.id, 1)
    await check_roles(membro, pontos)
    await interaction.response.send_message(f"🌟 {interaction.user.mention} deu +1 de reputação para {membro.mention}!")

@bot.tree.command(name="neg")
@app_commands.checks.cooldown(1, 3600, key=lambda i: i.user.id)
async def neg(interaction: discord.Interaction, membro: discord.Member):
    if membro.id == interaction.user.id:
        return await interaction.response.send_message("Você não pode negativar a si mesmo.", ephemeral=True)
    
    pontos = update_rep(membro.id, -1)
    await check_roles(membro, pontos)
    await interaction.response.send_message(f"💢 {interaction.user.mention} deu -1 de reputação para {membro.mention}!")

@bot.tree.command(name="perfil")
async def perfil(interaction: discord.Interaction, membro: discord.Member = None):
    membro = membro or interaction.user
    conn = get_connection()
    cur = conn.cursor()
    cur.execute('SELECT pontos FROM reputacao WHERE user_id = %s', (membro.id,))
    res = cur.fetchone()
    pontos = res[0] if res else 0
    cur.close()
    conn.close()

    if pontos >= 100: status, cor = "Trocador Oficial 💎", 0x00ffff
    elif pontos >= 50: status, cor = "Trocador Confiável ✅", 0x2ecc71
    elif pontos >= 10: status, cor = "Trocador Iniciante ✅", 0x9b59b6
    elif pontos <= -10: status, cor = "Trocador Perigoso ❌", 0xe74c3c
    else: status, cor = "Neutro", 0x95a5a6

    embed = discord.Embed(title=f"Perfil de {membro.name}", color=cor)
    embed.add_field(name="Reputação", value=str(pontos), inline=True)
    embed.add_field(name="Cargo de Troca", value=status, inline=True)
    embed.set_thumbnail(url=membro.display_avatar.url)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="limpar")
async def limpar(interaction: discord.Interaction, quantidade: int):
    if not any(role.name.lower() == "mods" for role in interaction.user.roles):
        return await interaction.response.send_message("Apenas mods podem usar isso.", ephemeral=True)
    await interaction.response.defer(ephemeral=True)
    await interaction.channel.purge(limit=quantidade)
    await interaction.followup.send(f"🧹 {quantidade} mensagens removidas.", ephemeral=True)

@bot.tree.command(name="setrep")
async def setrep(interaction: discord.Interaction, membro: discord.Member, pontos: int):
    if not any(role.name.lower() == "mods" for role in interaction.user.roles):
        return await interaction.response.send_message("Acesso negado.", ephemeral=True)
    
    conn = get_connection()
    cur = conn.cursor()
    cur.execute('INSERT INTO reputacao (user_id, pontos) VALUES (%s, %s) ON CONFLICT (user_id) DO UPDATE SET pontos = %s', (membro.id, pontos, pontos))
    conn.commit()
    cur.close()
    conn.close()
    
    await check_roles(membro, pontos)
    await interaction.response.send_message(f"Reputação de {membro.mention} ajustada para {pontos}.", ephemeral=True)

@bot.tree.command(name="top")
async def top(interaction: discord.Interaction):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute('SELECT user_id, pontos FROM reputacao ORDER BY pontos DESC LIMIT 10')
    rows = cur.fetchall()
    cur.close()
    conn.close()

    desc = ""
    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    for i, row in enumerate(rows):
        user = bot.get_user(row[0])
        name = user.name if user else f"ID: {row[0]}"
        desc += f"{medals[i]} **{name}** — {row[1]} pts\n"

    embed = discord.Embed(title="🏆 Top 10 Raiders Confiáveis", description=desc or "Ninguém no ranking ainda.", color=0xf1c40f)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="aviso", description="Envia um comunicado oficial com marcação @everyone")
@app_commands.describe(
    mensagem="O texto do aviso",
    titulo="Título opcional para criar um Embed",
    cor="Cor do Embed em Hex (ex: 00ff00 para verde). Deixe vazio para azul padrão."
)
async def aviso(
    interaction: discord.Interaction, 
    mensagem: str, 
    titulo: Optional[str] = None, 
    cor: Optional[str] = None
):
    # Verificação de permissão (apenas Mods ou Admins)
    is_mod = any(role.name.lower() == "mods" for role in interaction.user.roles)
    if not is_mod and not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("❌ Você não tem permissão para usar este comando.", ephemeral=True)

    # Tratamento da cor
    cor_final = 0x3498db # Azul padrão
    if cor:
        try:
            cor_final = int(cor.replace("#", ""), 16)
        except ValueError:
            pass

    await interaction.response.defer(ephemeral=True)

    try:
        if titulo:
            # Envia como Embed
            embed = discord.Embed(
                title=f"📢 {titulo}",
                description=mensagem,
                color=cor_final,
                timestamp=datetime.datetime.now()
            )
            if interaction.guild.icon:
                embed.set_thumbnail(url=interaction.guild.icon.url)
            
            embed.set_footer(text=f"Enviado por: {interaction.user.name}", icon_url=interaction.user.display_avatar.url)
            
            await interaction.channel.send(content="@everyone", embed=embed)
        else:
            # Envia como texto simples
            texto_formatado = f"📢 **AVISO - ARC RAIDERS BRASIL**\n\n@everyone\n\n{mensagem}"
            await interaction.channel.send(content=texto_formatado)

        await interaction.followup.send("✅ Aviso enviado com sucesso!", ephemeral=True)

    except Exception as e:
        await interaction.followup.send(f"❌ Erro ao enviar aviso: {e}", ephemeral=True)

# Variável global para calcular o uptime
start_time = time.time()

@bot.tree.command(name="status", description="Exibe o status técnico do bot e do sistema")
async def status(interaction: discord.Interaction):
    # Verificação de permissão (Mods ou Admins)
    is_mod = any(role.name.lower() == "mods" for role in interaction.user.roles)
    if not is_mod and not interaction.user.guild_permissions.administrator:
        return await interaction.response.send_message("❌ Acesso restrito aos protocolos de Staff.", ephemeral=True)

    # Cálculo de Uptime
    current_time = time.time()
    uptime_seconds = int(current_time - start_time)
    uptime_str = str(datetime.timedelta(seconds=uptime_seconds))

    # Teste de conexão com o Banco de Dados
    db_status = "🟢 Conectado"
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute('SELECT 1')
        cur.close()
        conn.close()
    except Exception:
        db_status = "🔴 Desconectado"

    # Informações de Latência
    ping = round(bot.latency * 1000)

    embed = discord.Embed(
        title="⚙️ STATUS DO TERMINAL - ARC RAIDERS BRASIL",
        color=0x2ecc71 if db_status == "🟢 Conectado" else 0xe74c3c,
        timestamp=datetime.datetime.now()
    )
    
    embed.add_field(name="🛰️ Latência (Ping)", value=f"`{ping}ms`", inline=True)
    embed.add_field(name="⏳ Uptime", value=f"`{uptime_str}`", inline=True)
    embed.add_field(name="🗄️ Banco de Dados (Postgres)", value=f"`{db_status}`", inline=False)
    embed.add_field(name="💻 Hospedagem", value="`Railway.app`", inline=True)
    embed.add_field(name="🐍 Versão Python", value="`3.11`", inline=True)

    if interaction.guild.icon:
        embed.set_thumbnail(url=interaction.guild.icon.url)
    
    embed.set_footer(text="Sistema operacional operando dentro dos parâmetros.")

    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="raid_post", description="Posta um recrutamento para Raid (Duo ou Trio)")
@app_commands.describe(
    tipo="Selecione Duo ou Trio",
    mapa="Qual mapa vocês vão jogar?",
    objetivo="O que pretendem fazer? (Ex: Farmar Fusion Core)"
)
@app_commands.choices(tipo=[
    app_commands.Choice(name="DUO (2 pessoas)", value="duo"),
    app_commands.Choice(name="TRIO (3 pessoas)", value="trio")
])
async def raid_post(interaction: discord.Interaction, tipo: app_commands.Choice[str], mapa: str, objetivo: str):
    vagas = 2 if tipo.value == "duo" else 3
    cat = 1486347910885937242 if tipo.value == "duo" else 1486348090741883114

# Cria a View APENAS aqui, e não no setup_hook
    view = RaidView(interaction.user, vagas, mapa, objetivo, cat, vagas) 
    await interaction.response.send_message(embed=view.gerar_embed(), view=view)

# --- EVENTOS DE CANAIS E TÓPICOS ---
@bot.event
async def on_thread_create(thread):
    # ID do canal de fórum/trocas
    if thread.parent_id == 1434310955004592360:
        view = discord.ui.View(timeout=None)
        btn = discord.ui.Button(
            label="Finalizar e Excluir Tópico", 
            style=discord.ButtonStyle.red,
            emoji="🗑️"
        )

        async def btn_callback(interaction: discord.Interaction):
            # Verifica se é o dono do tópico ou se tem cargo 'mods'
            is_mod = any(role.name.lower() == "mods" for role in interaction.user.roles)
            
            if interaction.user.id == thread.owner_id or is_mod:
                await interaction.response.defer() # Dá tempo ao bot para processar o log
                
                log_chan = bot.get_channel(1433136439456956576)
                
                # --- GERAÇÃO DO LOG TXT ---
                history_text = f"LOG DE TROCA - ARC RAIDERS BRASIL\nTópico: {thread.name}\nID: {thread.id}\nAutor: {thread.owner_id}\nFechado por: {interaction.user.name}\nData: {datetime.datetime.now().strftime('%d/%m/%Y %H:%M')}\n"
                history_text += "-"*50 + "\n\n"
                
                async for msg in thread.history(limit=None, oldest_first=True):
                    timestamp = msg.created_at.strftime('%d/%m/%Y %H:%M')
                    history_text += f"[{timestamp}] {msg.author.name}: {msg.content}\n"

                # Cria o arquivo em memória
                file_data = io.BytesIO(history_text.encode('utf-8'))
                log_file = discord.File(file_data, filename=f"troca-{thread.id}.txt")
                
                if log_chan:
                    await log_chan.send(
                        content=f"🗑️ **Tópico de Troca Encerrado**\n**Nome:** `{thread.name}`\n**Autor:** <@{thread.owner_id}>\n**Fechado por:** {interaction.user.mention}",
                        file=log_file
                    )
                
                await interaction.followup.send("Log gerado. Excluindo tópico...")
                await thread.delete()
            else:
                await interaction.response.send_message("❌ Apenas o autor da troca ou a Staff pode finalizar este tópico.", ephemeral=True)

        btn.callback = btn_callback
        view.add_item(btn)

        # Criando o Embed para a mensagem de boas-vindas da troca
        embed = discord.Embed(
            title="📦 NOVA TROCA INICIADA!",
            description=(
                f"Olá <@{thread.owner_id}>, bem-vindo ao sistema de trocas!\n\n"
                "🛡️ **Dicas de Segurança:**\n"
                "• Verifique a reputação usando `/perfil @membro` antes de negociar.\n"
                "• Use o comando `/rep @membro` **apenas após** a troca ser concluída.\n"
                "• Se for scammado, abra um ticket imediatamente e use `/neg @membro`.\n\n"
                "🚫 **Aviso sobre RMT:**\n"
                "Compra e venda por dinheiro real é **PROIBIDO** e resulta em banimento.\n\n"
                "⚠️ **Finalização:**\n"
                "Após concluir o negócio, clique no botão abaixo para encerrar o tópico."
            ),
            color=0xf39c12
        )
        
        embed.set_footer(text="ARC Raiders Brasil - Sistema de Trocas e Reputação")
        
        await thread.send(content=f"Atenção <@{thread.owner_id}>!", embed=embed, view=view)

@bot.event
async def on_voice_state_update(member, before, after):
    # IDs de geradores de canal
    gen_duo = 1486348560822960128
    gen_trio = 1486348629550825653
    
    # Categorias
    cat_duo_id = 1486347910885937242
    cat_trio_id = 1486348090741883114

    # 1. Lógica para CRIAR canais
    if after.channel:
        # Se entrou no gerador de DUO
        if after.channel.id == gen_duo:
            guild = member.guild
            category = guild.get_channel(cat_duo_id)
            
            new_channel = await guild.create_voice_channel(
                name=f"Duo: {member.name}", 
                category=category, 
                user_limit=2
            )
            await member.move_to(new_channel)
            
        # Se entrou no gerador de TRIO
        elif after.channel.id == gen_trio:
            guild = member.guild
            category = guild.get_channel(cat_trio_id)
            
            new_channel = await guild.create_voice_channel(
                name=f"Trio: {member.name}", 
                category=category, 
                user_limit=3
            )
            await member.move_to(new_channel)

    # 2. Lógica para DELETAR canais vazios
    if before.channel:
        # Verifica se o canal que o membro saiu é um dos criados pelo bot
        # Checamos se ele está dentro das categorias de Raid e se não é o canal gerador
        if before.channel.category_id in [cat_duo_id, cat_trio_id]:
            if before.channel.id not in [gen_duo, gen_trio]:
                # Se o canal ficou vazio, deleta
                if len(before.channel.members) == 0:
                    try:
                        await before.channel.delete()
                    except discord.NotFound:
                        pass
                    except Exception as e:
                        print(f"Erro ao deletar canal vazio: {e}")

bot.run(os.getenv('TOKEN'))