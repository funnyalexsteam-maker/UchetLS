import asyncio
import aiosqlite
from datetime import date
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# ================== НАСТРОЙКИ ==================
BOT_TOKEN = "8904597240:AAHdSPiWSYsbZGnbutftUgbQYJYi7MnhKB0"
ADMINS = [1132781927, 946294855]  # ID администраторов

GROUPS = {
    1: "Группа 1",
    2: "Группа 2",
    3: "Группа 3",
    4: "Группа 4"
}

# Готовые причины отсутствия
REASONS = [
    "Наряд",
    "Рапорт",
    "ПВК",
    "Командировка"
]

DB_NAME = "attendance.db"
# ===============================================

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())


class Form(StatesGroup):
    waiting_name = State()          # добавление человека
    waiting_reason = State()        # причина отсутствия


async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        # Список людей
        await db.execute("""
            CREATE TABLE IF NOT EXISTS people (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id INTEGER NOT NULL,
                full_name TEXT NOT NULL,
                UNIQUE(group_id, full_name)
            )
        """)
        # Отметки присутствия
        await db.execute("""
            CREATE TABLE IF NOT EXISTS marks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                day TEXT NOT NULL,
                person_id INTEGER NOT NULL,
                status TEXT NOT NULL,          -- 'present' или 'absent'
                reason TEXT,
                UNIQUE(day, person_id),
                FOREIGN KEY (person_id) REFERENCES people(id) ON DELETE CASCADE
            )
        """)
        await db.commit()


def is_admin(user_id: int) -> bool:
    return user_id in ADMINS


# ================== КЛАВИАТУРЫ ==================

def main_menu():
    builder = InlineKeyboardBuilder()
    builder.button(text="👥 Управление людьми", callback_data="manage")
    builder.button(text="✅ Отметить присутствие", callback_data="mark")
    builder.button(text="📊 Статистика", callback_data="stats")
    builder.adjust(1)
    return builder.as_markup()


def groups_keyboard(prefix: str):
    """prefix = manage / mark / stats"""
    builder = InlineKeyboardBuilder()
    for gid, name in GROUPS.items():
        builder.button(text=name, callback_data=f"{prefix}_{gid}")
    builder.button(text="« Назад", callback_data="back_main")
    builder.adjust(2)
    return builder.as_markup()


def people_manage_keyboard(group_id: int, people: list):
    builder = InlineKeyboardBuilder()
    for person in people:
        builder.button(
            text=f"❌ {person[1]}",
            callback_data=f"del_{person[0]}"
        )
    builder.button(text="➕ Добавить человека", callback_data=f"add_{group_id}")
    builder.button(text="« Назад", callback_data="manage")
    builder.adjust(1)
    return builder.as_markup()


def mark_person_keyboard(person_id: int):
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Присутствует", callback_data=f"status_{person_id}_present")
    builder.button(text="❌ Отсутствует", callback_data=f"status_{person_id}_absent")
    builder.adjust(2)
    return builder.as_markup()


# ================== КОМАНДЫ ==================

@dp.message(Command("start"))
async def cmd_start(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ У вас нет доступа.")
        return
    await message.answer(
        "👋 Бот учёта личного состава\n\nВыберите действие:",
        reply_markup=main_menu()
    )


@dp.callback_query(F.data == "back_main")
async def back_main(callback: CallbackQuery):
    await callback.message.edit_text(
        "👋 Бот учёта личного состава\n\nВыберите действие:",
        reply_markup=main_menu()
    )
    await callback.answer()


# ================== УПРАВЛЕНИЕ ЛЮДЬМИ ==================

@dp.callback_query(F.data == "manage")
async def manage_menu(callback: CallbackQuery):
    await callback.message.edit_text(
        "Выберите группу для управления списком людей:",
        reply_markup=groups_keyboard("manage")
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("manage_"))
async def manage_group(callback: CallbackQuery):
    group_id = int(callback.data.split("_")[1])
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            "SELECT id, full_name FROM people WHERE group_id = ? ORDER BY full_name",
            (group_id,)
        )
        people = await cursor.fetchall()

    text = f"<b>{GROUPS[group_id]}</b>\n\n"
    if people:
        text += "Список людей:\n" + "\n".join(f"• {p[1]}" for p in people)
    else:
        text += "Список пуст."

    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=people_manage_keyboard(group_id, people)
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("add_"))
async def add_person_start(callback: CallbackQuery, state: FSMContext):
    group_id = int(callback.data.split("_")[1])
    await state.update_data(group_id=group_id)
    await state.set_state(Form.waiting_name)
    await callback.message.edit_text(
        f"Введите фамилию и инициалы для <b>{GROUPS[group_id]}</b>\n"
        f"(пример: Иванов И.И.):",
        parse_mode="HTML"
    )
    await callback.answer()


@dp.message(Form.waiting_name)
async def add_person_finish(message: Message, state: FSMContext):
    name = message.text.strip()
    if len(name) < 3:
        await message.answer("Слишком короткое имя. Попробуйте ещё раз.")
        return

    data = await state.get_data()
    group_id = data["group_id"]

    async with aiosqlite.connect(DB_NAME) as db:
        try:
            await db.execute(
                "INSERT INTO people (group_id, full_name) VALUES (?, ?)",
                (group_id, name)
            )
            await db.commit()
            await message.answer(f"✅ Добавлен: <b>{name}</b>", parse_mode="HTML")
        except aiosqlite.IntegrityError:
            await message.answer("⚠️ Такой человек уже есть в этой группе.")

    await state.clear()
    # Возвращаем в меню группы
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            "SELECT id, full_name FROM people WHERE group_id = ? ORDER BY full_name",
            (group_id,)
        )
        people = await cursor.fetchall()

    await message.answer(
        f"<b>{GROUPS[group_id]}</b>",
        parse_mode="HTML",
        reply_markup=people_manage_keyboard(group_id, people)
    )


@dp.callback_query(F.data.startswith("del_"))
async def delete_person(callback: CallbackQuery):
    person_id = int(callback.data.split("_")[1])
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT group_id, full_name FROM people WHERE id = ?", (person_id,))
        row = await cursor.fetchone()
        if not row:
            await callback.answer("Человек не найден", show_alert=True)
            return
        group_id, name = row
        await db.execute("DELETE FROM people WHERE id = ?", (person_id,))
        await db.commit()

    await callback.answer(f"Удалён: {name}")
    # Обновляем список
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            "SELECT id, full_name FROM people WHERE group_id = ? ORDER BY full_name",
            (group_id,)
        )
        people = await cursor.fetchall()

    text = f"<b>{GROUPS[group_id]}</b>\n\n"
    if people:
        text += "Список людей:\n" + "\n".join(f"• {p[1]}" for p in people)
    else:
        text += "Список пуст."

    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=people_manage_keyboard(group_id, people)
    )


# ================== ОТМЕТКА ПРИСУТСТВИЯ ==================

@dp.callback_query(F.data == "mark")
async def mark_menu(callback: CallbackQuery):
    await callback.message.edit_text(
        "Выберите группу для отметки присутствия:",
        reply_markup=groups_keyboard("mark")
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("mark_"))
async def mark_group(callback: CallbackQuery):
    group_id = int(callback.data.split("_")[1])
    today = date.today().isoformat()

    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            "SELECT id, full_name FROM people WHERE group_id = ? ORDER BY full_name",
            (group_id,)
        )
        people = await cursor.fetchall()

        if not people:
            await callback.message.edit_text(
                f"В группе <b>{GROUPS[group_id]}</b> пока нет людей.\n"
                "Сначала добавьте их через «Управление людьми».",
                parse_mode="HTML",
                reply_markup=groups_keyboard("mark")
            )
            await callback.answer()
            return

        # Получаем уже сделанные отметки на сегодня
        cursor = await db.execute(
            "SELECT person_id, status FROM marks WHERE day = ?",
            (today,)
        )
        already = {row[0]: row[1] for row in await cursor.fetchall()}

    text = f"<b>{GROUPS[group_id]}</b> — отметка на {today}\n\n"
    builder = InlineKeyboardBuilder()

    for pid, name in people:
        status = already.get(pid)
        if status == "present":
            mark = "✅"
        elif status == "absent":
            mark = "❌"
        else:
            mark = "⬜"
        builder.button(text=f"{mark} {name}", callback_data=f"person_{pid}")

    builder.button(text="« Назад", callback_data="mark")
    builder.adjust(1)

    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())
    await callback.answer()


@dp.callback_query(F.data.startswith("person_"))
async def choose_status(callback: CallbackQuery):
    async def mark_group_from_id(callback: CallbackQuery, group_id: int):
        """Обновляет список отметок группы"""
        today = date.today().isoformat()
        async with aiosqlite.connect(DB_NAME) as db:
            cursor = await db.execute(
                "SELECT id, full_name FROM people WHERE group_id = ? ORDER BY full_name",
                (group_id,)
            )
            people = await cursor.fetchall()
            cursor = await db.execute(
                "SELECT person_id, status FROM marks WHERE day = ?",
                (today,)
            )
            already = {row[0]: row[1] for row in await cursor.fetchall()}

        text = f"<b>{GROUPS[group_id]}</b> — отметка на {today}\n\n"
        builder = InlineKeyboardBuilder()
        for pid, name in people:
            status = already.get(pid)
            mark = "✅" if status == "present" else "❌" if status == "absent" else "⬜"
            builder.button(text=f"{mark} {name}", callback_data=f"person_{pid}")
        builder.button(text="« Назад", callback_data="mark")
        builder.adjust(1)

        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())
    person_id = int(callback.data.split("_")[1])
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT full_name FROM people WHERE id = ?", (person_id,))
        row = await cursor.fetchone()
        name = row[0] if row else "Неизвестный"

    await callback.message.edit_text(
        f"Статус для: <b>{name}</b>",
        parse_mode="HTML",
        reply_markup=mark_person_keyboard(person_id)
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("status_"))
async def set_status(callback: CallbackQuery, state: FSMContext):
    _, person_id, status = callback.data.split("_")
    person_id = int(person_id)
    today = date.today().isoformat()

    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT full_name, group_id FROM people WHERE id = ?", (person_id,))
        row = await cursor.fetchone()
        if not row:
            await callback.answer("Человек удалён", show_alert=True)
            return
        name, group_id = row

    if status == "present":
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("""
                INSERT INTO marks (day, person_id, status, reason)
                VALUES (?, ?, 'present', NULL)
                ON CONFLICT(day, person_id) DO UPDATE SET status = 'present', reason = NULL
            """, (today, person_id))
            await db.commit()
        await callback.answer(f"✅ {name} — присутствует")
        await mark_group_from_id(callback, group_id)
    else:
        # Показываем кнопки с готовыми причинами
        builder = InlineKeyboardBuilder()
        for reason in REASONS:
            builder.button(text=reason, callback_data=f"reason_{person_id}_{reason}")
        builder.button(text="Другое", callback_data=f"reason_{person_id}_other")
        builder.button(text="« Назад", callback_data=f"person_{person_id}")
        builder.adjust(1)

        await callback.message.edit_text(
            f"❌ <b>{name}</b> отсутствует.\n\nВыберите причину:",
            parse_mode="HTML",
            reply_markup=builder.as_markup()
        )
        await callback.answer()
@dp.callback_query(F.data.startswith("reason_"))
async def set_reason(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split("_", 2)  # reason_ID_Причина
    person_id = int(parts[1])
    reason = parts[2]
    today = date.today().isoformat()

    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute("SELECT full_name, group_id FROM people WHERE id = ?", (person_id,))
        row = await cursor.fetchone()
        if not row:
            await callback.answer("Человек не найден", show_alert=True)
            return
        name, group_id = row

        if reason == "other":
            # Просим ввести свою причину
            await state.update_data(person_id=person_id, group_id=group_id, name=name)
            await state.set_state(Form.waiting_reason)
            await callback.message.edit_text(
                f"❌ {name} отсутствует.\n\nНапишите причину:"
            )
            await callback.answer()
            return

        # Сохраняем готовую причину
        await db.execute("""
            INSERT INTO marks (day, person_id, status, reason)
            VALUES (?, ?, 'absent', ?)
            ON CONFLICT(day, person_id) DO UPDATE SET status = 'absent', reason = excluded.reason
        """, (today, person_id, reason))
        await db.commit()

    await callback.answer(f"❌ {name} — {reason}")

    async def mark_group_from_id(callback: CallbackQuery, group_id: int):
        """Обновляет список отметок группы после изменения статуса"""
        today = date.today().isoformat()

        async with aiosqlite.connect(DB_NAME) as db:
            cursor = await db.execute(
                "SELECT id, full_name FROM people WHERE group_id = ? ORDER BY full_name",
                (group_id,)
            )
            people = await cursor.fetchall()

            cursor = await db.execute(
                "SELECT person_id, status FROM marks WHERE day = ?",
                (today,)
            )
            already = {row[0]: row[1] for row in await cursor.fetchall()}

        text = f"<b>{GROUPS[group_id]}</b> — отметка на {today}\n\n"
        builder = InlineKeyboardBuilder()

        for pid, name in people:
            status = already.get(pid)
            if status == "present":
                mark = "✅"
            elif status == "absent":
                mark = "❌"
            else:
                mark = "⬜"
            builder.button(text=f"{mark} {name}", callback_data=f"person_{pid}")

        builder.button(text="« Назад", callback_data="mark")
        builder.adjust(1)

        await callback.message.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=builder.as_markup()
        )
    await mark_group_from_id(callback, group_id)


@dp.message(Form.waiting_reason)
async def save_reason(message: Message, state: FSMContext):
    reason = message.text.strip()
    data = await state.get_data()
    person_id = data["person_id"]
    group_id = data["group_id"]
    name = data["name"]
    today = date.today().isoformat()

    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute("""
            INSERT INTO marks (day, person_id, status, reason)
            VALUES (?, ?, 'absent', ?)
            ON CONFLICT(day, person_id) DO UPDATE SET status = 'absent', reason = excluded.reason
        """, (today, person_id, reason))
        await db.commit()

    await state.clear()
    await message.answer(f"❌ {name} — отсутствует\nПричина: {reason}")

    # Показываем обновлённый список группы
    today = date.today().isoformat()
    async with aiosqlite.connect(DB_NAME) as db:
        cursor = await db.execute(
            "SELECT id, full_name FROM people WHERE group_id = ? ORDER BY full_name",
            (group_id,)
        )
        people = await cursor.fetchall()
        cursor = await db.execute(
            "SELECT person_id, status FROM marks WHERE day = ?",
            (today,)
        )
        already = {row[0]: row[1] for row in await cursor.fetchall()}

    text = f"<b>{GROUPS[group_id]}</b> — отметка на {today}\n\n"
    builder = InlineKeyboardBuilder()
    for pid, pname in people:
        status = already.get(pid)
        mark = "✅" if status == "present" else "❌" if status == "absent" else "⬜"
        builder.button(text=f"{mark} {pname}", callback_data=f"person_{pid}")
    builder.button(text="« Назад", callback_data="mark")
    builder.adjust(1)

    await message.answer(text, parse_mode="HTML", reply_markup=builder.as_markup())


# ================== СТАТИСТИКА ==================

@dp.callback_query(F.data == "stats")
async def stats_menu(callback: CallbackQuery):
    await callback.message.edit_text(
        "Выберите группу или общий итог:",
        reply_markup=groups_keyboard("stats")
    )
    # Добавляем кнопку общего итога
    builder = InlineKeyboardBuilder()
    for gid, name in GROUPS.items():
        builder.button(text=name, callback_data=f"stats_{gid}")
    builder.button(text="📈 Общий итог", callback_data="stats_total")
    builder.button(text="« Назад", callback_data="back_main")
    builder.adjust(2)
    await callback.message.edit_text(
        "Выберите группу или общий итог:",
        reply_markup=builder.as_markup()
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("stats_"))
async def show_stats(callback: CallbackQuery):
    today = date.today().isoformat()
    data = callback.data

    if data == "stats_total":
        # Общий итог
        text = f"📈 <b>Общий итог на {today}</b>\n\n"
        total_present = 0
        total_absent = 0
        total_people = 0
        reasons_count = {reason: 0 for reason in REASONS}
        reasons_count["Другое"] = 0

        async with aiosqlite.connect(DB_NAME) as db:
            for gid, gname in GROUPS.items():
                cursor = await db.execute(
                    "SELECT COUNT(*) FROM people WHERE group_id = ?", (gid,)
                )
                count = (await cursor.fetchone())[0]
                total_people += count

                cursor = await db.execute("""
                    SELECT m.status, COUNT(*) 
                    FROM marks m
                    JOIN people p ON p.id = m.person_id
                    WHERE m.day = ? AND p.group_id = ?
                    GROUP BY m.status
                """, (today, gid))
                rows = await cursor.fetchall()
                present = next((r[1] for r in rows if r[0] == "present"), 0)
                absent = next((r[1] for r in rows if r[0] == "absent"), 0)

                total_present += present
                total_absent += absent

                text += f"<b>{gname}</b>: ✅ {present}  ❌ {absent}  (всего {count})\n"

            # Считаем причины отсутствия
            cursor = await db.execute("""
                SELECT reason, COUNT(*) 
                FROM marks 
                WHERE day = ? AND status = 'absent'
                GROUP BY reason
            """, (today,))
            reason_rows = await cursor.fetchall()

            for reason, cnt in reason_rows:
                if reason in reasons_count:
                    reasons_count[reason] = cnt
                else:
                    reasons_count["Другое"] += cnt

        text += f"\n✅ <b>Всего присутствует: {total_present}</b>"
        text += f"\n❌ <b>Всего отсутствует: {total_absent}</b>"
        text += f"\n👥 <b>Всего в списках: {total_people}</b>"

        # Добавляем разбивку по причинам
        if total_absent > 0:
            text += "\n\n📋 <b>Причины отсутствия:</b>\n"
            for reason, cnt in reasons_count.items():
                if cnt > 0:
                    text += f"• {reason}: <b>{cnt}</b>\n"

    builder = InlineKeyboardBuilder()
    builder.button(text="« Назад", callback_data="stats")
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())
    await callback.answer()


# ================== ЗАПУСК ==================

async def main():
    await init_db()
    print("Бот запущен...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())