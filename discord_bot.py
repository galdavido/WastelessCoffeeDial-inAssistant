import discord
import os
import tempfile
from vision import analyze_coffee_bag
from rag import get_best_grind_setting
from database import SessionLocal, engine, Base
from models import Bean, Equipment, DialInLog
from dotenv import load_dotenv
from typing import Any

load_dotenv()

# Inicializáljuk az adatbázist induláskor
def init_db():
    try:
        Base.metadata.create_all(bind=engine)
        print("Adatbázis táblák létrehozva.")
    except Exception as e:
        print(f"DB init hiba: {e}")

# Seed adatok (egyszerűsített)
def seed_db():
    db = SessionLocal()
    try:
        if not db.query(Equipment).first():
            machine = Equipment(type="espresso_machine", brand="AVX", model="Hero Plus 2024")
            grinder = Equipment(type="grinder", brand="Kingrinder", model="K6")
            db.add_all([machine, grinder])
            db.commit()
            print("Alap eszközök hozzáadva.")
    except Exception as e:
        print(f"Seed hiba: {e}")
    finally:
        db.close()

# Futtassuk az init-et
init_db()
seed_db()

intents = discord.Intents.default()  # type: ignore[reportUnknownMemberType]
intents.message_content = True  # type: ignore[reportUnknownMemberType]
client = discord.Client(intents=intents)  # type: ignore[reportUnknownArgumentType]

@client.event
async def on_ready():
    print(f'BaristAI Discord Bot bejelentkezve mint {client.user}')  # type: ignore[reportUnknownMemberType]

@client.event
async def on_message(message):
    author: Any = message.author  # type: ignore[assignment]
    if author == client.user:
        return

    # Ha van attachment (kép), és az képfájl
    if message.attachments:  # type: ignore[reportUnknownMemberType]
        for attachment in message.attachments:  # type: ignore[reportUnknownMemberType]
            if attachment.content_type and attachment.content_type.startswith('image/'):  # type: ignore[reportUnknownMemberType, reportUnknownArgumentType]
                # Letöltjük a képet temp fájlba
                with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as temp_file:
                    await attachment.save(temp_file.name)  # type: ignore[reportUnknownMemberType, reportUnknownArgumentType]
                    temp_path = temp_file.name

                try:
                    # Elemzés
                    coffee_data = analyze_coffee_bag(temp_path)
                    if not coffee_data:
                        await message.reply("❌ Nem sikerült kinyerni adatokat a képből. Próbáld újra egy jobb minőségű fotóval!")  # type: ignore[reportUnknownMemberType]
                        return

                    # RAG keresés
                    recommendation = get_best_grind_setting(coffee_data)

                    # Válasz
                    coffee_info = f"☕ **{coffee_data.get('roaster', 'Unknown')} {coffee_data.get('name', 'Unknown')} {coffee_data.get('roast_date', 'Unknown')}**\n" \
                                  f"🌍 {coffee_data.get('origin', 'Unknown')} | {coffee_data.get('process', 'Unknown')} | {coffee_data.get('roast_level', 'Unknown')}"

                    response = f"{coffee_info}\n\n💡 **Javaslat az adatbázisból:**\n{recommendation}\n\n👍 Ha jó volt, reagálj thumbs up-pal, hogy elmentsük ezt a beállítást!"

                    sent_message = await message.reply(response)  # type: ignore[reportUnknownMemberType]

                    # Várunk reakcióra (egyszerű visszajelzés)
                    def check(reaction, user):
                        return user == author and str(reaction.emoji) == '👍' and reaction.message.id == sent_message.id  # type: ignore[comparison-overlap, reportUnknownMemberType]

                    try:
                        reaction, user = await client.wait_for('reaction_add', timeout=300.0, check=check)  # 5 perc  # type: ignore[reportUnknownMemberType, reportUnknownArgumentType]
                        # Ha thumbs up, kérdezzük meg a tényleges beállítást
                        await message.reply("👍 Szuper! Mi volt a tényleges darálási beállítás, amit használtál? Válaszolj pl. '36 klikk' vagy 'fine'.")  # type: ignore[reportUnknownMemberType]
                        
                        # Várunk a válaszra
                        def msg_check(m):
                            return m.author == user and m.channel == message.channel  # type: ignore[reportUnknownMemberType]
                        
                        try:
                            reply = await client.wait_for('message', timeout=120.0, check=msg_check)  # 2 perc  # type: ignore[reportUnknownMemberType, reportUnknownArgumentType]
                            actual_grind = reply.content.strip()
                            await save_dial_in_log(coffee_data, recommendation, author.name, actual_grind)  # type: ignore[attr-defined]
                            await message.reply(f"✅ Elmentve: '{actual_grind}' beállítás az adatbázisba!")  # type: ignore[reportUnknownMemberType]
                        except:
                            # Ha nem válaszol, mentsük az alapértelmezettet
                            await save_dial_in_log(coffee_data, recommendation, author.name)  # type: ignore[attr-defined]
                            await message.reply("⏰ Időtúllépés. Elmentettem az alapértelmezett javaslatot.")  # type: ignore[reportUnknownMemberType]
                    except:
                        pass  # Timeout vagy nem reagált

                finally:
                    # Töröljük a temp fájlt
                    os.unlink(temp_path)

async def save_dial_in_log(coffee_data, recommendation, user_name, actual_grind=None):
    """Új log mentése az adatbázisba (egyszerűsített)"""
    db = SessionLocal()  # type: ignore[reportUnknownVariableType]
    try:
        # Keressük vagy hozzuk létre a babot
        bean = db.query(Bean).filter(  # type: ignore[reportUnknownMemberType]
            Bean.name == coffee_data.get('name'),  # type: ignore[reportUnknownArgumentType]
            Bean.roaster == coffee_data.get('roaster')  # type: ignore[reportUnknownArgumentType]
        ).first()  # type: ignore[reportUnknownMemberType]
        if not bean:
            bean = Bean(  # type: ignore[reportUnknownVariableType]
                roaster=coffee_data.get('roaster', 'Unknown'),
                name=coffee_data.get('name', 'Unknown'),
                origin=coffee_data.get('origin', 'Unknown'),
                process=coffee_data.get('process', 'Unknown'),
                roast_level=coffee_data.get('roast_level', 'Unknown')
            )
            db.add(bean)  # type: ignore[reportUnknownMemberType]
            db.commit()  # type: ignore[reportUnknownMemberType]
            db.refresh(bean)  # type: ignore[reportUnknownMemberType]

        # Keressük az alapértelmezett eszközt (feltételezzük, hogy van)
        grinder = db.query(Equipment).filter(Equipment.type == 'grinder').first()  # type: ignore[reportUnknownMemberType]
        machine = db.query(Equipment).filter(Equipment.type == 'espresso_machine').first()  # type: ignore[reportUnknownMemberType]
        if not grinder or not machine:
            return  # Nincs eszköz, nem mentjük

        # Beállítás: ha megadták, használjuk, különben parse-oljuk
        if actual_grind:
            grind_setting = actual_grind
        else:
            grind_setting = "Unknown"
            if "Suggested Grind Setting:" in recommendation:
                try:
                    start = recommendation.find("Suggested Grind Setting:") + len("Suggested Grind Setting:")
                    end = recommendation.find("\n", start)
                    grind_setting = recommendation[start:end].strip()
                except:
                    pass
        
        dose_g = 16.0  # alapértelmezett

        log = DialInLog(  # type: ignore[reportUnknownVariableType]
            bean_id=bean.id,  # type: ignore[reportUnknownMemberType]
            grinder_id=grinder.id,  # type: ignore[reportUnknownMemberType]
            machine_id=machine.id,  # type: ignore[reportUnknownMemberType]
            grind_setting=grind_setting,
            dose_g=dose_g,
            rating=5,  # jó visszajelzés
            tasting_notes=f"Discord visszajelzés: {user_name} - {recommendation[:100]}..."
        )
        db.add(log)  # type: ignore[reportUnknownMemberType]
        db.commit()  # type: ignore[reportUnknownMemberType]
    finally:
        db.close()  # type: ignore[reportUnknownMemberType]

if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        print("DISCORD_TOKEN nincs beállítva!")
        exit(1)
    client.run(token)
