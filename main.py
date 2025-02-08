import discord
from discord.ext import commands, tasks
import json
import os
import traceback
from datetime import datetime, timedelta
from typing import Optional

CONFIG_FILE = 'config.json'
DATA_FILE = 'temp_roles.json'
ALLOWED_UNITS = {'s', 'm', 'h', 'd', 'w', 'y'}
DEFAULT_CONFIG = {
    "token": "here",
    "required_role_id": 1234567890,
    "log_id": 9876543210,
    "guild_id": 0,
    "safe_mode": True
}

class ConfigManager:
    @staticmethod
    def initialize():
        if not os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(DEFAULT_CONFIG, f, indent=4, ensure_ascii=False)
            print(f"تم إنشاء {CONFIG_FILE} يرجى تعبئة البيانات")
            exit()

        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            config = json.load(f)
            required_keys = ["token", "required_role_id", "log_id", "guild_id", "safe_mode"]
            for key in required_keys:
                if key not in config:
                    print(f"المفتاح '{key}' مفقود في ملف الإعدادات!")
                    exit()
            return config

config = ConfigManager.initialize()

class DataManager:
    @staticmethod
    def load():
        try:
            if not os.path.exists(DATA_FILE):
                with open(DATA_FILE, 'w', encoding='utf-8') as f:
                    json.dump({}, f, indent=4, ensure_ascii=False)
                return {}
            
            with open(DATA_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        
        except Exception as e:
            print(f"خطأ في تحميل الداتا بيس: {str(e)}")
            return {}

    @staticmethod
    def save(data):
        try:
            with open(DATA_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4, ensure_ascii=False, default=str)
            return True
        except Exception as e:
            print(f"خطأ في حفظ الداتا بيس: {str(e)}")
            return False

intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(
    command_prefix='!',
    intents=intents,
    help_command=None,
    case_insensitive=True
)

class TimeConverter:
    @staticmethod
    def convert(duration: str) -> int:
        if len(duration) < 1:
            raise ValueError("صيغة المدة غير صحيحة")
        
        unit = duration[-1].lower()
        if unit not in ALLOWED_UNITS:
            raise ValueError(f"وحدة زمنية غير مدعومة في الكود او غير صحيحة: {unit}")
        
        try:
            value = int(duration[:-1]) if len(duration) > 1 else 1
            if value <= 0:
                raise ValueError("المدة يجب أن تكون اكبر من صفر! ❌")
        except ValueError:
            raise ValueError("قيمة المدة غير صحيحة")
        
        multipliers = {
            's': 1,
            'm': 60,
            'h': 3600,
            'd': 86400,
            'w': 604800,
            'y': 31536000
        }
        return value * multipliers[unit]

class BackgroundTasks:
    @tasks.loop(seconds=30)
    async def check_roles(self):
        try:
            data = DataManager.load()
            guild_id = config.get('guild_id')
            if not guild_id:
                return
                
            guild = bot.get_guild(guild_id)
            if not guild:
                return

            log_channel = bot.get_channel(config.get('log_id'))
            if not log_channel:
                return

            for user_id, roles in list(data.items()):
                member = guild.get_member(int(user_id))
                if not member:
                    del data[user_id]
                    DataManager.save(data)
                    continue

                roles_to_remove = []
                for role_info in roles:
                    role = guild.get_role(role_info['role_id'])
                    if not role:
                        roles_to_remove.append(role_info)
                        continue

                    expires = datetime.fromisoformat(role_info['expires'])
                    if datetime.now() < expires:
                        continue

                    try:
                        await member.remove_roles(role)
                        await log_channel.send(
                            f"⏰ **رتبة منتهية**\n"
                            f"العضو: {member.mention}\n"
                            f"الرتبة: {role.mention}\n"
                            f"الإنتهاء: <t:{int(expires.timestamp())}:F>"
                        )
                    except discord.Forbidden:
                        await log_channel.send(f"❌ **خطأ في الصلاحيات** - لا يمكن إزالة الرتبة {role.mention} من {member.mention}")
                    except discord.HTTPException as e:
                        await log_channel.send(f"❌ **خطأ برمجي اثناء ازالة الرتبة. يرجى المحاولة لاحقا. ** - {e}")
                    finally:
                        roles_to_remove.append(role_info)

                for role_info in roles_to_remove:
                    if role_info in roles:
                        roles.remove(role_info)

                if not roles:
                    del data[user_id]
                else:
                    data[user_id] = roles

            DataManager.save(data)
        
        except Exception as e:
            traceback.print_exc()

@bot.tree.command(name="add_temp_role", description="إضافة رتبة مؤقتة لعضو")
@commands.has_role(config['required_role_id'])
async def add_temp_role(
    interaction: discord.Interaction,
    member: discord.Member,
    role: discord.Role,
    duration: str,
    reason: Optional[str] = "غير محدد"
):
    try:
        if config.get('safe_mode', True) and role >= interaction.guild.me.top_role:
            return await interaction.response.send_message(
                "⚠️ لا يمكن إضافة رتبة أعلى من رتبة البوت",
                ephemeral=True
            )

        if member.bot:
            return await interaction.response.send_message(
                "❌ لا يمكن إعطاء رتبة للبوتات ",
                ephemeral=True
            )

        if role in member.roles:
            return await interaction.response.send_message(
                "⚠️ العضو لديه الرتبة بالفعل",
                ephemeral=True
            )

        try:
            duration_sec = TimeConverter.convert(duration)
        except ValueError as e:
            return await interaction.response.send_message(
                f"❌ خطأ في المدة: {str(e)}",
                ephemeral=True
            )

        data = DataManager.load()
        user_roles = data.get(str(member.id), [])
        
        if any(r['role_id'] == role.id for r in user_roles):
            return await interaction.response.send_message(
                "⚠️ الرتبة مضافة مسبقاً في النظام",
                ephemeral=True
            )

        expires = datetime.now() + timedelta(seconds=duration_sec)
        new_role = {
            "member_id": member.id,
            "member_name": str(member),
            "role_id": role.id,
            "role_name": role.name,
            "expires": expires.isoformat(),
            "added_by": interaction.user.id,
            "added_by_name": str(interaction.user),
            "reason": reason
        }
        
        user_roles.append(new_role)
        data[str(member.id)] = user_roles
        
        if not DataManager.save(data):
            raise RuntimeError("فشل في حفظ البيانات")

        try:
            await member.add_roles(role)
        except discord.Forbidden:
            return await interaction.response.send_message(
                "❌ البوت لا يملك الصلاحيات لإضافة الرتبة!",
                ephemeral=True
            )
            
        await interaction.response.send_message(
            f"✅ تم إضافة {role.mention} لـ {member.mention}\n"
            f"المدة: `{duration}` - تنتهي في <t:{int(expires.timestamp())}:F>",
            ephemeral=True
        )

        try:
            await member.send(
                f"🔔 **إشعار رتبة مؤقتة**\n"
                f"السيرفر: {interaction.guild.name}\n"
                f"الرتبة: {role.name}\n"
                f"المدة: {duration}\n"
                f"السبب: {reason}"
            )
        except discord.HTTPException:
            pass

        log_channel = bot.get_channel(config['log_id'])
        if log_channel:
            await log_channel.send(
                f"📥 **إضافة رتبة مؤقتة**\n"
                f"المضيف: {interaction.user.mention}\n"
                f"العضو: {member.mention}\n"
                f"الرتبة: {role.mention}\n"
                f"المدة: {duration} - تنتهي في <t:{int(expires.timestamp())}:F>\n"
                f"السبب: {reason}"
            )

    except Exception as e:
        await interaction.response.send_message(
            f"❌ حدث خطأ: {str(e)}",
            ephemeral=True
        )
        traceback.print_exc()

@bot.tree.command(name="view_temp_roles", description="عرض الرتب المؤقتة لعضو معين")
@commands.has_role(config['required_role_id'])
async def view_temp_roles(interaction: discord.Interaction, member: discord.Member):
    data = DataManager.load()
    user_roles = data.get(str(member.id), [])

    if not user_roles:
        return await interaction.response.send_message(
            "📜 لا يوجد رتب مؤقتة لهذا العضو",
            ephemeral=True
        )

    embed = discord.Embed(title=f"الرتب المؤقتة لـ {member}", color=0x00ff00)
    for role_info in user_roles:
        role = interaction.guild.get_role(role_info['role_id'])
        expires = datetime.fromisoformat(role_info['expires'])
        added_by = interaction.guild.get_member(role_info['added_by'])
        added_by_mention = added_by.mention if added_by else f"مستخدم غير موجود ({role_info['added_by']})"
        
        embed.add_field(
            name=f"{role_info['role_name']} ({'مفعلة' if role else 'محذوفة'})",
            value=(
                f"**الإنتهاء:** <t:{int(expires.timestamp())}:F>\n"
                f"**المضيف:** {added_by_mention}\n"
                f"**السبب:** {role_info['reason']}"
            ),
            inline=False
        )

    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="remove_temp_role", description="إزالة رتبة مؤقتة من عضو معين")
@commands.has_role(config['required_role_id'])
async def remove_temp_role(
    interaction: discord.Interaction,
    member: discord.Member,
    role: discord.Role
):
    try:
        data = DataManager.load()
        user_roles = data.get(str(member.id), [])

        new_roles = [r for r in user_roles if r['role_id'] != role.id]

        if len(new_roles) == len(user_roles):
            return await interaction.response.send_message(
                "⚠️ الرتبة غير موجودة في السجل",
                ephemeral=True
            )

        data[str(member.id)] = new_roles
        if not DataManager.save(data):
            return await interaction.response.send_message(
                "❌ فشل في حفظ البيانات بعد إزالة الرتبة",
                ephemeral=True
            )

        try:
            if role in member.roles:
                await member.remove_roles(role)
        except discord.Forbidden:
            return await interaction.response.send_message(
                "❌ البوت لا يملك الصلاحيات لإزالة الرتبة!",
                ephemeral=True
            )
            
        await interaction.response.send_message(
            f"✅ تم إزالة {role.name} من {member.mention}",
            ephemeral=True
        )

        log_channel = bot.get_channel(config['log_id'])
        if log_channel:
            await log_channel.send(
                f"📤 **إزالة رتبة مؤقتة**\n"
                f"العضو: {member.mention}\n"
                f"الرتبة: {role.mention}\n"
                f"أزيلت بواسطة: {interaction.user.mention}"
            )
    except Exception as e:
        await interaction.response.send_message(
            f"❌ حدث خطأ: {str(e)}",
            ephemeral=True
        )
        traceback.print_exc()

@bot.event
async def on_application_command_error(interaction: discord.Interaction, error: discord.DiscordException):
    if isinstance(error, commands.MissingRole):
        await interaction.response.send_message(
            "❌ ليست لديك الصلاحيات الكافية لأستخدام الامر",
            ephemeral=True
        )
    elif isinstance(error, commands.BotMissingPermissions):
        await interaction.response.send_message(
            "❌ البوت لا يملك الصلاحيات اللازمة!",
            ephemeral=True
        )
    else:
        await interaction.response.send_message(
            f"❌ حدث خطأ غير متوقع: {str(error)}",
            ephemeral=True
        )
        traceback.print_exc()

@bot.event
async def on_ready():
    try:
        print(f'Bot {bot.user} Is online')
        print(
        """
  _____              _            
 / ____|            (_)           
| (___    ___  _ __  _   ___  ___ 
 \___ \  / _ \| '__|| | / _ \/ __|
 ____) ||  __/| |   | ||  __/\__ \
|_____/  \___||_|   |_| \___||___/
                                  
                                  

        """
              )
    
        synced = await bot.tree.sync()
        print(f"تم مزامنة {len(synced)} أمر بنجاح جميع الانظمة تعمل بشكل كامل 🟢")
        if not BackgroundTasks().check_roles.is_running():
            BackgroundTasks().check_roles.start()
    except Exception as e:
        print(f"فشلت المزامنة يرجى التحقق من الكود بعض الانظمة لا تعمل 🟠: {e}")

bot.run(config['token'])
