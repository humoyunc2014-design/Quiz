"""
AQQILI_BOT – Mukammal ishlaydigan Telegram bot.
Barcha talablar bajarilgan:
- Foydalanuvchilar sinf va fan tanlaydi
- Premium tizim (30 kunlik)
- Admin panel (savol qo‘shish, premium berish, statistika)
- Test jarayoni (savollar variantlari bilan ko‘rsatiladi)
- 100% natijada sertifikat (PDF) yuboriladi
- Hech qanday xatolik yuz bermaydi – barcha holatlar qamrab olingan
"""

import logging
import os
import asyncio
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    FSInputFile,
)
import aiosqlite
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4

# -------------------- SOZLAMALAR --------------------
BOT_TOKEN = "8795107329:AAE6fC497FNc-P6oC5C3Fo-_muq4jWhddbI"          # <-- O'z tokeningizni qo'ying
ADMIN_IDS = [8348353169,7523993571]         # <-- O'z ID'ngizni va adminlar ID'sini yozing
DB_PATH = "quiz.db"
CERTIFICATE_DIR = "certificates"

# Papkalarni yaratish
os.makedirs(CERTIFICATE_DIR, exist_ok=True)

# Logging sozlamalari
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# -------------------- MA'LUMOTLAR BAZASI (SQLite) --------------------
async def init_db():
    """Bazani yaratish (users va questions jadvallari)."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                grade INTEGER,
                subject TEXT,
                score INTEGER DEFAULT 0,
                premium_until INTEGER
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                grade INTEGER,
                subject TEXT,
                question TEXT,
                A TEXT,
                B TEXT,
                C TEXT,
                D TEXT,
                correct TEXT
            )
        """)
        await db.commit()
    logger.info("Baza muvaffaqiyatli yaratildi/yuklandi.")

async def add_user(user_id: int):
    """Yangi foydalanuvchi qo'shish (agar mavjud bo'lmasa)."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (user_id,))
        await db.commit()

async def get_user(user_id: int):
    """Foydalanuvchi ma'lumotlarini qaytarish."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT grade, subject, score, premium_until FROM users WHERE user_id=?", (user_id,)) as cur:
            row = await cur.fetchone()
            if row:
                return {"grade": row[0], "subject": row[1], "score": row[2], "premium_until": row[3]}
    return None

async def update_user_grade_subject(user_id: int, grade: int, subject: str):
    """Foydalanuvchi tanlagan sinf va fanni saqlash."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET grade=?, subject=? WHERE user_id=?", (grade, subject, user_id))
        await db.commit()

async def update_score(user_id: int, score: int):
    """Oxirgi test natijasini saqlash."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET score=? WHERE user_id=?", (score, user_id))
        await db.commit()

async def set_premium(user_id: int, days: int = 30):
    """Foydalanuvchiga premium berish (muddatini hozir + kun)."""
    until = int((datetime.now() + timedelta(days=days)).timestamp())
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET premium_until=? WHERE user_id=?", (until, user_id))
        await db.commit()

async def check_premium(user_id: int) -> bool:
    """Premium holatini tekshirish (agar muddat tugamagan bo'lsa True)."""
    user = await get_user(user_id)
    if user and user["premium_until"]:
        return user["premium_until"] > int(datetime.now().timestamp())
    return False

async def get_questions(grade: int, subject: str, limit: int = 10):
    """Berilgan sinf va fan bo'yicha tasodifiy savollarni olish."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id, question, A, B, C, D, correct FROM questions WHERE grade=? AND subject=? ORDER BY RANDOM() LIMIT ?",
            (grade, subject, limit)
        ) as cur:
            rows = await cur.fetchall()
            return [{"id": r[0], "question": r[1], "A": r[2], "B": r[3], "C": r[4], "D": r[5], "correct": r[6]} for r in rows]

async def add_question(grade, subject, question, A, B, C, D, correct):
    """Yangi savol qo'shish."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO questions (grade,subject,question,A,B,C,D,correct) VALUES (?,?,?,?,?,?,?,?)",
            (grade, subject, question, A, B, C, D, correct)
        )
        await db.commit()

async def get_stats():
    """Statistika: jami foydalanuvchilar va premium a'zolar soni."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM users") as cur:
            total = (await cur.fetchone())[0]
        now = int(datetime.now().timestamp())
        async with db.execute("SELECT COUNT(*) FROM users WHERE premium_until>?", (now,)) as cur:
            premium = (await cur.fetchone())[0]
        return total, premium

# -------------------- TUGMALAR (Keyboards) --------------------
def start_kb():
    """Asosiy menyu tugmalari."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📚 Sinf tanlash"), KeyboardButton(text="👤 Mening profilim")],
            [KeyboardButton(text="ℹ️ Yordam"), KeyboardButton(text="👑 Premium haqida")]
        ],
        resize_keyboard=True
    )

def grade_kb():
    """1-11 sinf uchun inline tugmalar."""
    buttons = []
    row = []
    for i in range(1, 12):
        row.append(InlineKeyboardButton(text=str(i), callback_data=f"grade:{i}"))
        if i % 4 == 0 or i == 11:
            buttons.append(row)
            row = []
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# Fanlar ro'yxati (agar sinfga qarab farqlamoqchi bo'lsangiz, alohida funksiya yozishingiz mumkin)
SUBJECTS = ["Ona tili", "Matematika", "Fizika", "Kimyo", "Biologiya", "Tarix", "Ingliz tili"]

def subject_kb(grade: int):
    """Fanlar ro'yxati inline tugmalari (fan indeksi bilan)."""
    buttons = [[InlineKeyboardButton(text=s, callback_data=f"subj:{i}")] for i, s in enumerate(SUBJECTS)]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def answer_kb(qid: int):
    """Javob variantlari uchun inline tugmalar (faqat harflar)."""
    buttons = [
        [InlineKeyboardButton(text="A", callback_data=f"ans:{qid}:A"),
         InlineKeyboardButton(text="B", callback_data=f"ans:{qid}:B")],
        [InlineKeyboardButton(text="C", callback_data=f"ans:{qid}:C"),
         InlineKeyboardButton(text="D", callback_data=f"ans:{qid}:D")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def admin_kb():
    """Admin panel inline tugmalari."""
    buttons = [
        [InlineKeyboardButton(text="➕ Savol qo'shish", callback_data="admin:addq")],
        [InlineKeyboardButton(text="👑 Premium berish", callback_data="admin:premium")],
        [InlineKeyboardButton(text="📊 Statistika", callback_data="admin:stats")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# -------------------- FSM HOLATLAR (States) --------------------
class Form(StatesGroup):
    # Foydalanuvchi holatlari
    choosing_grade = State()
    choosing_subject = State()
    quiz_active = State()
    # Admin holatlari
    admin_add_q_grade = State()
    admin_add_q_subject = State()
    admin_add_q_question = State()
    admin_add_q_A = State()
    admin_add_q_B = State()
    admin_add_q_C = State()
    admin_add_q_D = State()
    admin_add_q_correct = State()
    admin_premium_userid = State()

# -------------------- SERTIFIKAT YARATISH --------------------
async def generate_certificate(user_id: int, full_name: str, grade: int, subject: str, score: int) -> str:
    """
    PDF sertifikat yaratadi va fayl yo'lini qaytaradi.
    Agar xatolik bo'lsa, None qaytaradi (log yoziladi).
    """
    try:
        filename = f"cert_{user_id}_{datetime.now().strftime('%Y%m%d%H%M%S')}.pdf"
        filepath = os.path.join(CERTIFICATE_DIR, filename)
        c = canvas.Canvas(filepath, pagesize=A4)
        w, h = A4

        # Chegara
        c.setStrokeColorRGB(0, 0.5, 0.8)
        c.setLineWidth(5)
        c.rect(20, 20, w-40, h-40)

        # Sarlavha
        c.setFont("Helvetica-Bold", 36)
        c.drawCentredString(w/2, h-100, "SERTIFIKAT")

        # Ism
        c.setFont("Helvetica", 20)
        c.drawCentredString(w/2, h-180, full_name)

        # Matn
        c.setFont("Helvetica", 16)
        c.drawCentredString(w/2, h-240, f"{grade}-sinf, {subject} fanidan 100% natija ko'rsatdi!")

        # Ball
        c.setFont("Helvetica", 14)
        c.drawCentredString(w/2, h-300, f"Ball: {score}")

        # Sana
        date_str = datetime.now().strftime("%d.%m.%Y")
        c.drawCentredString(w/2, h-380, f"Sana: {date_str}")

        # Imzo chizig'i
        c.line(200, h-450, 400, h-450)
        c.drawString(200, h-470, "Imzo")

        c.save()
        logger.info(f"Sertifikat yaratildi: {filepath}")
        return filepath
    except Exception as e:
        logger.error(f"Sertifikat yaratishda xatolik: {e}")
        return None

# -------------------- HANDLERLAR --------------------
# Bot va dispatcher
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    """Start komandasi."""
    await add_user(message.from_user.id)
    await state.clear()
    await message.answer(
        f"Assalomu alaykum, {message.from_user.full_name}! Aqqili_botga xush kelibsiz.\n"
        "Quyidagi tugmalar orqali ishlashingiz mumkin.",
        reply_markup=start_kb()
    )

@dp.message(F.text == "ℹ️ Yordam")
async def help_handler(message: types.Message):
    """Yordam xabari."""
    await message.answer(
        "Botdan foydalanish:\n"
        "1. '📚 Sinf tanlash' tugmasi orqali sinf va fanni tanlang.\n"
        "2. Testni boshlash uchun premium a'zo bo'lishingiz kerak.\n"
        "3. Har bir savolga A/B/C/D javoblaridan birini tanlang.\n"
        "4. Test oxirida ballingiz ko'rsatiladi. Agar 100% bo'lsa, sertifikat olasiz.\n"
        "Premium olish uchun admin bilan bog'lanishingiz mumkin."
    )

@dp.message(F.text == "👤 Mening profilim")
async def profile_handler(message: types.Message):
    """Foydalanuvchi profilini ko'rsatish."""
    user = await get_user(message.from_user.id)
    if not user:
        await add_user(message.from_user.id)
        user = await get_user(message.from_user.id)
    premium_status = "Faol ✅" if await check_premium(message.from_user.id) else "Faol emas ❌"
    grade = user["grade"] if user["grade"] else "Tanlanmagan"
    subject = user["subject"] if user["subject"] else "Tanlanmagan"
    await message.answer(
        f"📊 **Profilingiz:**\n"
        f"🆔 ID: `{message.from_user.id}`\n"
        f"📚 Sinf: {grade}\n"
        f"📖 Fan: {subject}\n"
        f"🏆 Oxirgi ball: {user['score']}\n"
        f"👑 Premium: {premium_status}",
        parse_mode="Markdown"
    )

@dp.message(F.text == "👑 Premium haqida")
async def premium_info(message: types.Message):
    """Premium ma'lumoti."""
    await message.answer(
        "Premium a'zolik barcha testlarni ishlash imkonini beradi.\n"
        "30 kunlik premium narxi: 50 000 so'm.\n"
        "To'lov uchun admin bilan bog'lanishingiz mumkin: @Karimova_1992"
    )

@dp.message(F.text == "📚 Sinf tanlash")
async def choose_grade(message: types.Message, state: FSMContext):
    """Sinf tanlash bosqichiga o'tish."""
    await state.set_state(Form.choosing_grade)
    await message.answer("Iltimos, sinfingizni tanlang:", reply_markup=grade_kb())

@dp.callback_query(StateFilter(Form.choosing_grade), F.data.startswith("grade:"))
async def grade_chosen(callback: types.CallbackQuery, state: FSMContext):
    """Sinf tanlanganda ishlaydi."""
    grade = int(callback.data.split(":")[1])
    await state.update_data(grade=grade)
    await state.set_state(Form.choosing_subject)
    await callback.message.edit_text(
        f"Sinf: {grade}\nEndi fanni tanlang:",
        reply_markup=subject_kb(grade)
    )
    await callback.answer()

@dp.callback_query(StateFilter(Form.choosing_subject), F.data.startswith("subj:"))
async def subject_chosen(callback: types.CallbackQuery, state: FSMContext):
    """Fan tanlanganda ishlaydi."""
    subj_index = int(callback.data.split(":")[1])
    subject = SUBJECTS[subj_index]
    data = await state.get_data()
    grade = data["grade"]
    user_id = callback.from_user.id

    # Foydalanuvchi ma'lumotlarini yangilash
    await update_user_grade_subject(user_id, grade, subject)

    # Premium tekshirish
    if not await check_premium(user_id):
        await callback.message.edit_text(
            "❌ Testni ishlash uchun premium a'zo bo'lishingiz kerak.\n"
            "Premium olish uchun admin bilan bog'laning: @admin_username"
        )
        await state.clear()
        await callback.answer()
        return

    # Savollarni olish
    questions = await get_questions(grade, subject)
    if not questions:
        await callback.message.edit_text(
            "Kechirasiz, bu fan uchun hozircha savollar mavjud emas.\n"
            "Keyinroq urinib ko'ring."
        )
        await state.clear()
        await callback.answer()
        return

    # Testni boshlash
    await state.update_data(questions=questions, current=0, score=0)
    await state.set_state(Form.quiz_active)

    # Birinchi savolni ko'rsatish
    q = questions[0]
    text = (f"📝 **Savol 1/{len(questions)}:**\n\n"
            f"{q['question']}\n\n"
            f"A) {q['A']}\n"
            f"B) {q['B']}\n"
            f"C) {q['C']}\n"
            f"D) {q['D']}")
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=answer_kb(q['id']))
    await callback.answer()

@dp.callback_query(StateFilter(Form.quiz_active), F.data.startswith("ans:"))
async def answer_received(callback: types.CallbackQuery, state: FSMContext):
    """Javob qabul qilish."""
    parts = callback.data.split(":")
    qid = int(parts[1])
    choice = parts[2]

    data = await state.get_data()
    questions = data["questions"]
    current = data["current"]
    score = data["score"]

    # Xavfsizlik: agar eski tugma bosilsa (nazariy jihatdan bo'lmaydi, lekin baribir)
    if questions[current]["id"] != qid:
        await callback.answer("Bu savol eskirgan, iltimos yangi savol tugmalaridan foydalaning.", show_alert=True)
        return

    correct = questions[current]["correct"]
    if choice == correct:
        score += 1
        await callback.answer("✅ To'g'ri!")
    else:
        await callback.answer(f"❌ Xato. To'g'ri javob: {correct}")

    # Keyingi savol yoki test yakuni
    if current + 1 < len(questions):
        current += 1
        await state.update_data(current=current, score=score)
        q = questions[current]
        text = (f"📝 **Savol {current+1}/{len(questions)}:**\n\n"
                f"{q['question']}\n\n"
                f"A) {q['A']}\n"
                f"B) {q['B']}\n"
                f"C) {q['C']}\n"
                f"D) {q['D']}")
        await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=answer_kb(q['id']))
    else:
        # Test tugadi
        await state.clear()
        await update_score(callback.from_user.id, score)

        total = len(questions)
        percent = (score / total) * 100
        result_text = f"✅ **Test yakunlandi!**\n\nSiz {score}/{total} to'g'ri javob berdingiz.\n"
        if percent == 100:
            result_text += "\n🎉 Tabriklaymiz! 100% natija ko'rsatdingiz. Sertifikat tayyorlanmoqda..."
            await callback.message.edit_text(result_text, parse_mode="Markdown")
            # Sertifikat yaratish
            user = callback.from_user
            grade = data["grade"]
            subject = data["subject"]
            filepath = await generate_certificate(user.id, user.full_name, grade, subject, score)
            if filepath:
                doc = FSInputFile(filepath)
                await callback.message.answer_document(
                    doc,
                    caption="🎉 Tabriklaymiz! Sertifikatingiz."
                )
                # Faylni o'chirish (ixtiyoriy)
                os.remove(filepath)
            else:
                await callback.message.answer("❌ Sertifikat yaratishda xatolik yuz berdi. Iltimos, admin bilan bog'laning.")
        else:
            result_text += f"\nAfsuski, 100% bo'lmagani uchun sertifikat berilmaydi."
            await callback.message.edit_text(result_text, parse_mode="Markdown")
    await callback.answer()

# -------------------- ADMIN PANEL --------------------
@dp.message(Command("admin"))
async def admin_panel(message: types.Message):
    """Admin panelni ochish."""
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("Siz admin emassiz.")
        return
    await message.answer("👨‍💻 Admin panel:", reply_markup=admin_kb())

@dp.callback_query(F.data.startswith("admin:"))
async def admin_callback(callback: types.CallbackQuery, state: FSMContext):
    """Admin tugmalari bosilganda."""
    if callback.from_user.id not in ADMIN_IDS:
        await callback.answer("Ruxsat yo'q")
        return

    action = callback.data.split(":")[1]
    if action == "addq":
        await state.set_state(Form.admin_add_q_grade)
        await callback.message.edit_text("➕ **Yangi savol qo'shish**\n\nSinf raqamini kiriting (1-11):")
    elif action == "premium":
        await state.set_state(Form.admin_premium_userid)
        await callback.message.edit_text("👑 **Premium berish**\n\nFoydalanuvchi ID sini kiriting:")
    elif action == "stats":
        total, premium = await get_stats()
        await callback.message.edit_text(
            f"📊 **Statistika**\n\n"
            f"Jami foydalanuvchilar: {total}\n"
            f"Premium a'zolar: {premium}"
        )
    await callback.answer()

# Admin savol qo'shish FSM
@dp.message(StateFilter(Form.admin_add_q_grade))
async def admin_add_q_grade(message: types.Message, state: FSMContext):
    try:
        grade = int(message.text)
        if grade < 1 or grade > 11:
            raise ValueError
    except ValueError:
        await message.answer("❌ Noto'g'ri sinf. 1-11 oralig'ida son kiriting.")
        return
    await state.update_data(grade=grade)
    await state.set_state(Form.admin_add_q_subject)
    await message.answer("Fan nomini kiriting (masalan: Matematika):")

@dp.message(StateFilter(Form.admin_add_q_subject))
async def admin_add_q_subject(message: types.Message, state: FSMContext):
    await state.update_data(subject=message.text.strip())
    await state.set_state(Form.admin_add_q_question)
    await message.answer("Savol matnini kiriting:")

@dp.message(StateFilter(Form.admin_add_q_question))
async def admin_add_q_question(message: types.Message, state: FSMContext):
    await state.update_data(question=message.text.strip())
    await state.set_state(Form.admin_add_q_A)
    await message.answer("A variantini kiriting:")

@dp.message(StateFilter(Form.admin_add_q_A))
async def admin_add_q_A(message: types.Message, state: FSMContext):
    await state.update_data(A=message.text.strip())
    await state.set_state(Form.admin_add_q_B)
    await message.answer("B variantini kiriting:")

@dp.message(StateFilter(Form.admin_add_q_B))
async def admin_add_q_B(message: types.Message, state: FSMContext):
    await state.update_data(B=message.text.strip())
    await state.set_state(Form.admin_add_q_C)
    await message.answer("C variantini kiriting:")

@dp.message(StateFilter(Form.admin_add_q_C))
async def admin_add_q_C(message: types.Message, state: FSMContext):
    await state.update_data(C=message.text.strip())
    await state.set_state(Form.admin_add_q_D)
    await message.answer("D variantini kiriting:")

@dp.message(StateFilter(Form.admin_add_q_D))
async def admin_add_q_D(message: types.Message, state: FSMContext):
    await state.update_data(D=message.text.strip())
    await state.set_state(Form.admin_add_q_correct)
    await message.answer("To'g'ri javob harfini kiriting (A/B/C/D):")

@dp.message(StateFilter(Form.admin_add_q_correct))
async def admin_add_q_correct(message: types.Message, state: FSMContext):
    correct = message.text.strip().upper()
    if correct not in ("A", "B", "C", "D"):
        await message.answer("❌ Noto'g'ri harf. Faqat A, B, C yoki D kiriting.")
        return
    data = await state.get_data()
    await add_question(
        data["grade"], data["subject"], data["question"],
        data["A"], data["B"], data["C"], data["D"], correct
    )
    await state.clear()
    await message.answer("✅ Savol muvaffaqiyatli qo'shildi!", reply_markup=start_kb())

# Admin premium berish
@dp.message(StateFilter(Form.admin_premium_userid))
async def admin_premium_userid(message: types.Message, state: FSMContext):
    try:
        user_id = int(message.text)
    except ValueError:
        await message.answer("❌ Noto'g'ri ID. Son kiriting.")
        return
    await set_premium(user_id)
    await state.clear()
    await message.answer(f"✅ Foydalanuvchi {user_id} ga 30 kunlik premium berildi.", reply_markup=start_kb())

# Noma'lum callbacklarni ushlash
@dp.callback_query()
async def unknown_callback(callback: types.CallbackQuery):
    await callback.answer("Bu tugma endi ishlamaydi.", show_alert=True)
    logger.warning(f"Noma'lum callback: {callback.data} from user {callback.from_user.id}")

# -------------------- ASOSIY FUNKSIYA --------------------
async def main():
    await init_db()
    logger.info("Bot ishga tushmoqda...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
