import discord
from discord import app_commands
from discord.ext import commands
import psycopg2
import datetime
import os
import io
from dotenv import load_dotenv

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

class ARC_Bot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.all() # Necessário para gerenciar cargos e canais
        super().__init__(command_prefix="/", intents=intents)

    async def setup_hook(self):
        # Registra as Views persistentes (para botões não pararem de funcionar)
        self.add_view(RegrasView())
        self.add_view(SuporteView())
        await self.tree.sync()

bot = ARC_Bot()

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

# --- COMANDOS ---

@bot.tree.command(name="ajuda", description="Exibe o terminal de suporte")
async def ajuda(interaction: discord.Interaction):
    embed = discord.Embed(
        title="🛰️ TERMINAL DE SUPORTE - ARC RAIDERS BRASIL",
        description="Bem-vindo ao sistema de auxílio automatizado.\n\n**PS:** Comandos de troca funcionam apenas no canal de trocas.",
        color=0x3498db
    )
    embed.add_field(name="📦 SISTEMA DE TROCAS", value="🌟 `/rep membro` - Dá +1 de reputação positiva.\n💢 `/neg membro` - Dá -1 de reputação negativa.\n👤 `/perfil membro` - Consulta a ficha do raider.\n🏆 `/top` - Ranking dos mais confiáveis.", inline=False)
    embed.add_field(name="📡 COMUNICAÇÃO DE RAID", value="🚨 `/raid` → selecione o mapa e número de vagas.\n• 1 vaga = DUO\n• 2 vagas = TRIO", inline=False)
    
    is_mod = any(role.name.lower() == "mods" for role in interaction.user.roles)
    is_admin = interaction.user.guild_permissions.administrator

    if is_mod or is_admin:
        embed.add_field(name="🛠️ PROTOCOLOS DE COMANDO (STAFF)", value="📢 `/falar texto` - Anúncios oficiais.\n🧹 `/limpar quantidade` - Limpa mensagens.\n🚨 `/denunciar membro tipo motivo` - Blacklist.\n📜 `/setrep membro pontos` - Ajusta reputação.\n⚙️ `/status` - Status do bot.", inline=False)

    if interaction.guild.icon:
        embed.set_thumbnail(url=interaction.guild.icon.url)
    
    embed.set_footer(text=f"Developer: {interaction.user.name} | Sponsors: !Gio, WARCELUS, lari nunes", icon_url=interaction.user.display_avatar.url)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="postar_regras", description="Posta o sistema de regras")
async def postar_regras(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator: return
    embed = discord.Embed(title="📜 REGRAS DO SERVIDOR", description="Clique no botão abaixo para aceitar as regras e liberar o servidor.", color=0x3498db)
    await interaction.channel.send(embed=embed, view=RegrasView())
    await interaction.response.send_message("Mensagem de regras enviada.", ephemeral=True)

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

# --- EVENTOS DE CANAIS E TÓPICOS ---

@bot.event
async def on_thread_create(thread):
    if thread.parent_id == 1434310955004592360:
        view = discord.ui.View(timeout=None)
        btn = discord.ui.Button(label="Finalizar e Excluir", style=discord.ButtonStyle.red)

        async def btn_callback(interaction: discord.Interaction):
            is_mod = any(role.name.lower() == "mods" for role in interaction.user.roles)
            if interaction.user.id == thread.owner_id or is_mod:
                log_chan = bot.get_channel(1433136439456956576)
                await log_chan.send(f"📦 Troca Finalizada: {thread.name} (Autor: <@{thread.owner_id}>)")
                await thread.delete()
            else:
                await interaction.response.send_message("Você não tem permissão para fechar este tópico.", ephemeral=True)

        btn.callback = btn_callback
        view.add_item(btn)

        await thread.send(
            content=f"Nova Troca Iniciada!\nOlá <@{thread.owner_id}>, bem-vindo ao sistema de trocas!Dicas de Segurança:\nVerifique a reputação de alguém usando o comando /perfil @membro antes fazer uma troca.\n\nUse o comando /rep @membro apenas após a troca ser concluída com sucesso.\n\nApós finalizada a troca, clique abaixo no botão para finalizar e excluir o tópico.\n\nSe por acaso for scammado, abra um ticket acionando nossos mods imediatamente e use o comando /neg @membro para negativar o raider.\n\nRMT: Compra e venda de itens com dinheiro real é PROIBIDO e passivo de banimento aqui e no jogo, cuida.",
            view=view
        )

@bot.event
async def on_voice_state_update(member, before, after):
    # IDs de geradores de canal
    gen_duo = 1486348560822960128
    gen_trio = 1486348629550825653
    
    # Categorias
    cat_duo = 1486347910885937242
    cat_trio = 1486348090741883114

    if after.channel:
        if after.channel.id == gen_duo:
            category = bot.get_channel(cat_duo)
            ch = await member.guild.create_voice_channel(name=f"Duo: {member.name}", category=category, user_limit=2)
            await member.move_to(ch)
        elif after.channel.id == gen_trio:
            category = bot.get_channel(cat_trio)
            ch = await member.guild.create_voice_channel(name=f"Trio: {member.name}", category=category, user_limit=3)
            await member.move_to(ch)

    # Deletar canais vazios
    if before.channel and "Duo:" in before.channel.name or "Trio:" in before.channel.name:
        if len(before.channel.members) == 0:
            await before.channel.delete()

bot.run(os.getenv('TOKEN'))