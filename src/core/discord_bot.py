import discord
import os
import tempfile
from ..ai.vision import analyze_coffee_bag
from ..ai.rag import get_best_grind_setting
from ..database.database import SessionLocal, engine, Base
from ..database.models import Bean, Equipment, DialInLog
from dotenv import load_dotenv
from typing import Any, Dict

load_dotenv()


# Initialize the database on startup
def init_db():
    try:
        Base.metadata.create_all(bind=engine)
        print("Database tables created.")
    except Exception as e:
        print(f"DB init error: {e}")


# Seed data (simplified)
def seed_db():
    db = SessionLocal()
    try:
        if not db.query(Equipment).first():
            machine = Equipment(
                type="espresso_machine", brand="AVX", model="Hero Plus 2024"
            )
            grinder = Equipment(type="grinder", brand="Kingrinder", model="K6")
            db.add_all([machine, grinder])
            db.commit()
            print("Basic equipment added.")
    except Exception as e:
        print(f"Seed error: {e}")
    finally:
        db.close()


# Run the init
init_db()
seed_db()

intents = discord.Intents.default()  # type: ignore[reportUnknownMemberType]
intents.message_content = True  # type: ignore[reportUnknownMemberType]
client = discord.Client(intents=intents)  # type: ignore[reportUnknownArgumentType]


@client.event
async def on_ready():
    print(f"BaristAI Discord Bot logged in as {client.user}")  # type: ignore[reportUnknownMemberType]


async def save_dial_in_log(
    coffee_data: Dict[str, Any],
    recommendation: str,
    user_name: str,
    actual_grind: str | None = None,
):
    """Save new log to database (simplified)"""
    db = SessionLocal()  # type: ignore[reportUnknownVariableType]
    try:
        # Find or create the bean
        bean = (
            db.query(Bean)
            .filter(  # type: ignore[reportUnknownMemberType]
                Bean.name == coffee_data.get("name"),  # type: ignore[reportUnknownArgumentType]
                Bean.roaster == coffee_data.get("roaster"),  # type: ignore[reportUnknownArgumentType]
            )
            .first()
        )  # type: ignore[reportUnknownMemberType]
        if not bean:
            bean = Bean(  # type: ignore[reportUnknownVariableType]
                roaster=coffee_data.get("roaster", "Unknown"),
                name=coffee_data.get("name", "Unknown"),
                origin=coffee_data.get("origin", "Unknown"),
                process=coffee_data.get("process", "Unknown"),
                roast_level=coffee_data.get("roast_level", "Unknown"),
            )
            db.add(bean)  # type: ignore[reportUnknownMemberType]
            db.commit()  # type: ignore[reportUnknownMemberType]
            db.refresh(bean)  # type: ignore[reportUnknownMemberType]

        # Find the default equipment (assume it exists)
        grinder = db.query(Equipment).filter(Equipment.type == "grinder").first()  # type: ignore[reportUnknownMemberType]
        machine = (
            db.query(Equipment).filter(Equipment.type == "espresso_machine").first()
        )  # type: ignore[reportUnknownMemberType]
        if not grinder or not machine:
            return  # No equipment, don't save

        # Setting: if provided, use it, otherwise parse
        if actual_grind:
            grind_setting = actual_grind
        else:
            grind_setting = "Unknown"
            if "Suggested Grind Setting:" in recommendation:
                try:
                    start = recommendation.find("Suggested Grind Setting:") + len(
                        "Suggested Grind Setting:"
                    )
                    end = recommendation.find("\n", start)
                    grind_setting = recommendation[start:end].strip()
                except Exception:
                    pass

        dose_g = 16.0  # default

        log = DialInLog(  # type: ignore[reportUnknownVariableType]
            bean_id=bean.id,  # type: ignore[reportUnknownMemberType]
            grinder_id=grinder.id,  # type: ignore[reportUnknownMemberType]
            machine_id=machine.id,  # type: ignore[reportUnknownMemberType]
            grind_setting=grind_setting,
            dose_g=dose_g,
            rating=5,  # good feedback
            tasting_notes=f"Discord feedback: {user_name} - {recommendation[:100]}...",
        )
        db.add(log)  # type: ignore[reportUnknownMemberType]
        db.commit()  # type: ignore[reportUnknownMemberType]
    finally:
        db.close()  # type: ignore[reportUnknownMemberType]


@client.event
async def on_message(message: Any):
    author: Any = message.author  # type: ignore[assignment]
    if author == client.user:
        return

    # Handle equipment setting commands
    if message.content.startswith("!set_grinder "):  # type: ignore[attr-defined]
        parts = message.content.split(" ", 2)  # type: ignore[attr-defined]
        if len(parts) >= 3:
            brand = parts[1]
            model = " ".join(parts[2:])  # In case model has spaces
            db = SessionLocal()
            try:
                grinder = (
                    db.query(Equipment).filter(Equipment.type == "grinder").first()
                )
                if grinder:
                    grinder.brand = brand
                    grinder.model = model  # type: ignore[assignment]
                else:
                    grinder = Equipment(type="grinder", brand=brand, model=model)
                    db.add(grinder)
                db.commit()
                await message.reply(f"✅ Grinder updated to {brand} {model}")  # type: ignore[reportUnknownMemberType]
            except Exception as e:
                await message.reply(f"❌ Error updating grinder: {e}")  # type: ignore[reportUnknownMemberType]
            finally:
                db.close()
        else:
            await message.reply("❌ Usage: !set_grinder <brand> <model>")  # type: ignore[reportUnknownMemberType]
        return

    if message.content.startswith("!set_machine "):  # type: ignore[attr-defined]
        parts = message.content.split(" ", 2)  # type: ignore[attr-defined]
        if len(parts) >= 3:
            brand = parts[1]
            model = " ".join(parts[2:])
            db = SessionLocal()
            try:
                machine = (
                    db.query(Equipment)
                    .filter(Equipment.type == "espresso_machine")
                    .first()
                )
                if machine:
                    machine.brand = brand
                    machine.model = model  # type: ignore[assignment]
                else:
                    machine = Equipment(
                        type="espresso_machine", brand=brand, model=model
                    )
                    db.add(machine)
                db.commit()
                await message.reply(f"✅ Espresso machine updated to {brand} {model}")  # type: ignore[reportUnknownMemberType]
            except Exception as e:
                await message.reply(f"❌ Error updating machine: {e}")  # type: ignore[reportUnknownMemberType]
            finally:
                db.close()
        else:
            await message.reply("❌ Usage: !set_machine <brand> <model>")  # type: ignore[reportUnknownMemberType]
        return

    if message.content == "!show_equipment":  # type: ignore[attr-defined]
        db = SessionLocal()
        try:
            grinder = db.query(Equipment).filter(Equipment.type == "grinder").first()
            machine = (
                db.query(Equipment).filter(Equipment.type == "espresso_machine").first()
            )
            grinder_info = f"{grinder.brand} {grinder.model}" if grinder else "Not set"
            machine_info = f"{machine.brand} {machine.model}" if machine else "Not set"
            await message.reply(
                f"🔧 **Current Equipment:**\n• Grinder: {grinder_info}\n• Espresso Machine: {machine_info}"
            )  # type: ignore[reportUnknownMemberType]
        except Exception as e:
            await message.reply(f"❌ Error retrieving equipment: {e}")  # type: ignore[reportUnknownMemberType]
        finally:
            db.close()
        return

    # If there is an attachment (image), and it's an image file
    if message.attachments:  # type: ignore[reportUnknownMemberType]
        for attachment in message.attachments:  # type: ignore[reportUnknownMemberType]
            if attachment.content_type and attachment.content_type.startswith("image/"):  # type: ignore[reportUnknownMemberType, reportUnknownArgumentType]
                # Download the image to a temp file
                with tempfile.NamedTemporaryFile(
                    delete=False, suffix=".jpg"
                ) as temp_file:
                    await attachment.save(temp_file.name)  # type: ignore[reportUnknownMemberType, reportUnknownArgumentType]
                    temp_path = temp_file.name

                try:
                    # Analysis
                    coffee_data = analyze_coffee_bag(temp_path)
                    if not coffee_data:
                        await message.reply(
                            "❌ Failed to extract data from the image. Try again with a better quality photo!"
                        )  # type: ignore[reportUnknownMemberType]
                        return

                    # RAG search
                    recommendation = get_best_grind_setting(coffee_data)

                    # Response
                    coffee_info = (
                        f"☕ **{coffee_data.get('roaster', 'Unknown')} {coffee_data.get('name', 'Unknown')} {coffee_data.get('roast_date', 'Unknown')}**\n"
                        f"🌍 {coffee_data.get('origin', 'Unknown')} | {coffee_data.get('process', 'Unknown')} | {coffee_data.get('roast_level', 'Unknown')}"
                    )

                    response = f"{coffee_info}\n\n💡 **Recommendation from the database:**\n{recommendation}\n\n👍 If it was good, react with thumbs up to save this setting!"

                    sent_message = await message.reply(response)  # type: ignore[reportUnknownMemberType]

                    # Wait for reaction (simple feedback)
                    def check(reaction: Any, user: Any) -> bool:
                        return (
                            user == author
                            and str(reaction.emoji) == "👍"
                            and reaction.message.id == sent_message.id
                        )  # type: ignore[reportUnknownMemberType]

                    try:
                        reaction, user = await client.wait_for(
                            "reaction_add", timeout=300.0, check=check
                        )  # 5 minutes  # type: ignore[reportUnknownMemberType, reportUnknownArgumentType]
                        # If thumbs up, ask for the actual setting
                        await message.reply(
                            "👍 Great! What was the actual grind setting you used? Reply e.g. '36 clicks' or 'fine'."
                        )  # type: ignore[reportUnknownMemberType]

                        # Wait for the response
                        def msg_check(m: Any) -> bool:
                            return m.author == user and m.channel == message.channel  # type: ignore[reportUnknownMemberType]

                        try:
                            reply = await client.wait_for(
                                "message", timeout=120.0, check=msg_check
                            )  # 2 minutes  # type: ignore[reportUnknownMemberType, reportUnknownArgumentType]
                            actual_grind = reply.content.strip()
                            await save_dial_in_log(
                                coffee_data, recommendation, author.name, actual_grind
                            )  # type: ignore[arg-type]
                            await message.reply(
                                f"✅ Saved: '{actual_grind}' setting to the database!"
                            )  # type: ignore[reportUnknownMemberType]
                        except Exception:
                            # If no response, save the default
                            await save_dial_in_log(
                                coffee_data, recommendation, author.name
                            )  # type: ignore[arg-type]
                            await message.reply(
                                "⏰ Timeout. Saved the default recommendation."
                            )  # type: ignore[reportUnknownMemberType]
                    except Exception:
                        pass  # Timeout or didn't react

                finally:
                    # Delete the temp file
                    os.unlink(temp_path)


if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        print("DISCORD_TOKEN not set!")
        exit(1)
    client.run(token)
