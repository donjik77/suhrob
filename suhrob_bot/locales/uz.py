TEXTS = {
    "uz": {
        # Common
        "back": "⬅️ Orqaga",
        "cancel": "❌ Bekor qilish",
        "confirm": "✅ Tasdiqlash",
        "edit": "✏️ O'zgartirish",
        "save": "💾 Saqlash",
        "yes": "✅ Ha",
        "no": "❌ Yo'q",
        # Start / welcome
        "welcome": "🏠 Assalomu alaykum, <b>{name}</b>!\n\nSuhrob HOUSE botiga xush kelibsiz.\nMen sizga mukammal uy topishda yordam beraman.\n\nQanday boshlamoqchisiz? 👇",
        "main_menu": "Asosiy menyu",
        # Client main menu buttons
        "btn_search": "🔍 Uy qidirish",
        "btn_favorites": "⭐ Saralangan",
        "btn_contact": "📞 Aloqa",
        "btn_consultation": "💬 Konsultatsiya",
        "btn_notifications": "🔔 Bildirishnomalar",
        "btn_help": "ℹ️ Yordam",
        # Search flow
        "search_type": "Qanday uy qidiryapsiz?",
        "type_apartment": "🏢 Kvartira",
        "type_house": "🏡 Hovli",
        "type_commercial": "🏪 Tijorat",
        "search_district": "Qaysi tumanni tanlaysiz?",
        "district_other": "🌍 Boshqa tuman",
        "district_input": "Tuman nomini kiriting:",
        "search_rooms": "Necha xonali uy kerak?",
        "rooms_any": "Farqi yo'q",
        "search_price": "Byudjet qancha? (AQSh dollarida)",
        "price_range_1": "$0 - $30,000",
        "price_range_2": "$30,000 - $60,000",
        "price_range_3": "$60,000 - $100,000",
        "price_range_4": "$100,000 - $200,000",
        "price_range_5": "$200,000+",
        "price_custom": "💰 O'z narximni kiritish",
        "price_custom_prompt": "Narx oralig'ini kiriting\n\nMisol: 50000-80000 yoki 100000 gacha\nFaqat USD da kiriting.",
        "price_parse_error": "Narxni to'g'ri formatda kiriting.\nMisol: 50000-80000 yoki 100000 gacha",
        # Search results
        "results_found": "✅ Sizga mos {count} ta variant topildi:",
        "results_not_found": "😔 Aynan mos variant topilmadi.\n\nLekin sizga yaqin variantlar bor:",
        "results_none": "😔 Hech qanday variant topilmadi.\n\nKeyinroq qayta urinib ko'ring.",
        "btn_new_search": "🔄 Yangi qidiruv",
        "btn_save_all": "⭐ Hammasini saqlash",
        "btn_other_params": "🔄 Boshqa parametrlar",
        "btn_notify_new": "🔔 Yangi chiqsa, xabar bering",
        # Property card
        "property_card": (
            "🏠 <b>{title}</b>\n\n"
            "📍 <b>Manzil:</b> {district}{address}\n"
            "💰 <b>Narxi:</b> ${price_usd} (~{price_uzs:,} so'm)\n"
            "🚪 <b>Xonalar:</b> {rooms}\n"
            "{floor_info}"
            "{area_info}"
            "{features}"
            "{description}"
            "👤 <b>Agent:</b> {agent_name}\n"
            "━━━━━━━━━━━━"
        ),
        "floor_info": "🏢 Qavat: {floor}/{total_floors}\n",
        "area_info": "📐 Maydoni: {area} m²\n",
        "btn_contact_agent": "📞 Bog'lanish",
        "btn_save_property": "⭐ Saqlash",
        "btn_share": "📤 Ulashish",
        "btn_ai_ask": "💬 Savol berish (AI)",
        "btn_mortgage": "💰 Ipoteka kalkulyatori",
        "btn_remove_favorite": "💔 O'chirish",
        # Agent contact
        "agent_contact": "📞 Agent ma'lumotlari:\n\nIsm: {name}\nTelefon: {phone}\nTelegram: {username}",
        "agent_notify_new_client": "💬 Yangi mijoz: {client_name}\nQiziqdi: {property_title}",
        "hot_lead_notify": (
            "🔥 <b>Yangi qaynoq mijoz!</b>\n\n"
            "👤 {client_name}\n"
            "📊 Sifat: {score}/100\n\n"
            "💰 Byudjet: {budget}\n"
            "📍 Tuman: {districts}\n"
            "🚪 Xonalar: {rooms}\n"
            "⏱ Muddat: {timeline}\n"
            "💳 To'lov: {payment_method}\n\n"
            "📝 AI xulosasi:\n{summary}"
        ),
        # Favorites
        "favorites_empty": "⭐ Saralanganlar bo'sh.\n\nUy qidirish orqali sevimli uylarni saqlang.",
        "favorites_title": "⭐ Saralangan uylar ({count} ta):",
        "favorite_saved": "⭐ Saralanganlar ro'yxatiga qo'shildi!",
        "favorite_already": "⭐ Bu uy allaqachon saralanganlar ro'yxatida!",
        "favorite_removed": "💔 Saralanganlardan o'chirildi.",
        # Subscription blocked
        "service_blocked_client": "🔒 Hozircha xizmat vaqtincha to'xtatilgan. Iltimos, keyinroq urinib ko'ring.",
        "service_blocked_agent": "🔒 Obuna to'lovi kerak. Direktor bilan bog'laning.",
        "subscription_payment_required": (
            "🔒 <b>Bot obunasi muddati tugagan.</b>\n\n"
            "Botdan foydalanishni davom ettirish uchun obuna to'lovini amalga oshiring. "
            "To'lov usulini tanlang:"
        ),
        # Agent main menu
        "agent_menu_welcome": "👋 Salom, {name}!\n\nSizning panelingiz:",
        "btn_add_property": "➕ Yangi uy qo'shish",

        "btn_my_properties": "📋 Mening uylarim",
        "btn_scheduled_posts": "📅 Rejalashtirilgan postlar",
        "btn_stats": "📊 Statistika",
        "btn_settings": "⚙️ Sozlamalar",
        "btn_my_clients": "🔥 Mening mijozlarim",
        "btn_all_clients": "🔥 Barcha mijozlar",
        "btn_instagram": "📷 Instagram ulash",
        # Director main menu additions
        "btn_agents_management": "👥 Agentlar boshqaruvi",
        "btn_agent_rating": "👥 Agentlar reytingi",
        "btn_all_properties": "🏢 Barcha uylar",
        "btn_subscription": "💳 Obuna holati",
        "btn_full_stats": "📈 To'liq statistika",
        "btn_my_profile": "👤 Mening profilim",
        "btn_shared_profile": "⚙️ Mening profilim",
        # Developer main menu additions
        "btn_issue_invoice": "💰 Hisob chiqarish",
        "btn_confirm_payments": "✅ To'lovlarni tasdiqlash",
        "btn_companies": "🏢 Kompaniyalar",
        "btn_system_settings": "⚙️ Tizim sozlamalari",
        # Agent personal settings
        "agent_settings_menu": "⚙️ Sozlamalar\n\nIsm: {name}\nTelefon: {phone}\n\nNimani o'zgartirmoqchisiz?",
        "agent_settings_name_prompt": "Yangi ismingizni kiriting (mijozlarga ko'rsatiladi):",
        "agent_settings_phone_prompt": "Telefon raqamingizni kiriting:\nMisol: +998901234567",
        "agent_settings_saved": "✅ {field} yangilandi: {value}",
        # All properties (director/developer)
        "all_props_title": "🏢 Barcha uylar (jami: {total})",
        "all_props_empty": "🏢 Hozircha uylar yo'q.",
        # Add property flow
        "add_prop_instruction": (
            "➕ <b>Yangi uy qo'shish</b>\n\n"
            "Uy haqida barcha ma'lumotni <b>bitta xabarda</b> yozing va rasmlarni yuboring.\n\n"
            "Misol:\n"
            "<i>Mirzo-Ulug'bek tumani, kvartira, 3 xona, 5/9 qavat, 75 m², "
            "narxi 65000$, Uzbekiston ko'chasi 15, evro remont, ipoteka bor</i>\n\n"
            "📸 Rasmlar va videoni ham yuboring.\n"
            "✅ Hammasi tayyor bo'lgach /done yozing."
        ),
        "add_prop_photo_received": "📸 {count} ta rasm qabul qilindi. Ko'proq yuboring yoki /done yozing.",
        "add_prop_parsing": "⏳ Ma'lumotlar aniqlanmoqda...",
        "add_prop_error_no_photos": "❌ Kamida 1 ta rasm yuboring.",
        "add_prop_error_no_text": "❌ Uy haqida matn kiriting.",
        # Add property FSM
        "add_prop_start": "Yangi uy qo'shish boshlandi. Quyidagi savollarga javob bering.",
        "add_prop_type": "Mulk turini tanlang:",
        "add_prop_district": "Tumanni tanlang yoki yangi nom kiriting:",
        "add_prop_district_new": "➕ Yangi tuman qo'shish",
        "add_prop_address": "Aniq manzilni kiriting (ixtiyoriy):\n\n/skip — o'tkazib yuborish",
        "add_prop_rooms": "Xonalar sonini kiriting (raqam):",
        "add_prop_rooms_error": "Iltimos, raqam kiriting (masalan: 3)",
        "add_prop_floor": "Qavat raqamini kiriting (ixtiyoriy):\n\n/skip — o'tkazib yuborish",
        "add_prop_total_floors": "Jami qavatlar sonini kiriting (ixtiyoriy):\n\n/skip — o'tkazib yuborish",
        "add_prop_area": "Maydonni kiriting m² da (ixtiyoriy):\n\n/skip — o'tkazib yuborish",
        "add_prop_price": "Narxni USD da kiriting (faqat raqam):\nMisol: 65000",
        "add_prop_price_error": "Iltimos, raqam kiriting. Misol: 65000",
        "add_prop_description": "Tavsif kiriting:",
        "add_prop_photos": "Rasmlarni yuboring (1 dan 10 tagacha).\n\nBarchasini yuborgach /done yozing.",
        "add_prop_photos_count": "📸 {count} ta rasm qabul qilindi.",
        "add_prop_videos": "Video fayllarini yuboring (ixtiyoriy, maksimal 2 ta).\n\n/skip — o'tkazib yuborish\n/done — tugallash",
        "add_prop_preview": "👁 Ko'rinish:\n\n{card}\n\nNima qilasiz?",
        "add_prop_saved": "✅ Uy muvaffaqiyatli saqlandi! (ID: #{prop_id})",
        "add_prop_when_publish": "Kanalga qachon publikatsiya qilamiz?",
        "btn_publish_now": "📢 Hozir",
        "btn_schedule_post": "⏰ Rejalashtirish",
        "btn_save_only": "💾 Faqat bazaga saqlash",
        "published_success": "✅ Kanal {channel}ga muvaffaqiyatli e'lon qilindi!",
        "published_scheduled": "⏰ {dt} da e'lon qilinishi rejalashtirildi.",
        "published_saved_only": "💾 Faqat bazaga saqlandi. E'lon qilinmadi.",
        "schedule_date_prompt": "Sana va vaqtni kiriting (format: DD.MM.YYYY HH:MM):\nMisol: 25.06.2026 14:00",
        "schedule_date_error": "Noto'g'ri format. Misol: 25.06.2026 14:00",
        # My properties list
        "my_props_title": "📋 Sizning uylaringiz (jami: {total})",
        "my_props_empty": "📋 Sizda hali uy yo'q.\n\nYangi uy qo'shish uchun ➕ tugmasini bosing.",
        "prop_status_active": "faol",
        "prop_status_sold": "sotilgan",
        "prop_status_hidden": "yashirilgan",
        "prop_type_apartment": "🏢",
        "prop_type_house": "🏡",
        "prop_type_commercial": "🏪",
        "btn_view": "👁 Ko'rish",
        "btn_edit": "✏️ Tahrirlash",
        "btn_delete": "🗑 O'chirish",
        "btn_change_status": "🔄 Status o'zgartirish",
        "btn_republish": "📢 Qayta e'lon qilish",
        "prop_deleted": "🗑 Uy o'chirildi.",
        "prop_delete_confirm": "Haqiqatan ham o'chirmoqchimisiz?",
        # Statistics
        "stats_agent_title": "📊 Sizning statistikangiz (oxirgi 30 kun)",
        "stats_active_props": "🏠 Faol uylar: {count}",
        "stats_sold_props": "✅ Sotilgan: {count}",
        "stats_views": "👁 Ko'rishlar: {count:,}",
        "stats_inquiries": "💬 Mijoz so'rovlari: {count}",
        "stats_contacts": "📞 Bog'lanishlar: {count}",
        "stats_top_searches": "🔥 Eng ko'p qidirilgan:",
        # Subscription
        "sub_status_active": "✅ Faol",
        "sub_status_pending": "⏳ To'lov kutilmoqda",
        "sub_status_expired": "❌ Muddati tugagan",
        "sub_status_blocked": "🔒 Bloklangan",
        "sub_info": "💳 Obuna holati\n\nStatus: {status}\nDavr: {start} — {end}\nNarx: ${price}",
        "btn_pay": "💳 To'lov qilish",
        "payment_method_select": "💳 To'lov usulini tanlang:",
        "btn_pay_click": "💳 Click",
        "btn_pay_humo": "💳 Humo",
        "btn_pay_uzcard": "💳 UzCard",
        "btn_pay_crypto": "₿ Kripto valyuta",
        "payment_instructions_card": (
            "💳 {method} orqali to'lov\n\n"
            "Karta raqami: {card}\n"
            "Karta egasi: {holder}\n"
            "Summa: ${price_usd} (~{price_uzs:,} so'm)\n\n"
            "To'lovni amalga oshiring va chek rasmini shu yerga yuboring."
        ),
        "payment_instructions_crypto": (
            "₿ Kripto valyuta orqali to'lov\n\n"
            "Tarmoq: {network}\n"
            "Manzil: {address}\n"
            "Summa: ${price_usd}\n\n"
            "To'lovni amalga oshiring va tranzaksiya tasdiqlangach skrinshotni yuboring."
        ),
        "payment_proof_received": "✅ Chekingiz qabul qilindi. Tez orada tasdiqlanadi.",
        "payment_confirmed": "✅ To'lov qabul qilindi! Bot ishga tushdi.\nYangi davr: {start} — {end}",
        "payment_rejected": "❌ To'lov rad etildi.\nSabab: {reason}",
        # Developer payment confirmation
        "dev_new_payment": (
            "💰 Yangi to'lov!\n\nKompaniya: {company}\nSumma: ${price}\nUsul: {method}"
        ),
        "btn_confirm_payment": "✅ Tasdiqlash",
        "btn_reject_payment": "❌ Rad etish",
        "reject_reason_prompt": "Rad etish sababini kiriting:",
        # Notifications
        "notify_3days": (
            "⚠️ 3 kundan so'ng obuna tugaydi.\n\n"
            "To'lov ${price} (~{price_uzs:,} so'm)."
        ),
        "notify_expired_director": "🔒 Obuna muddati tugadi. Bot bloklandi. To'lovni amalga oshiring va chekni yuboring.",
        "notify_expired_dev": "🚨 Kompaniya {company} bloklandi. To'lov hali kelmadi.",
        "notify_paid_all": "✅ To'lov qabul qilindi! Bot ishga tushdi. Yangi davr: {start} — {end}",
        # Invoice
        "invoice_select_company": "💰 Hisob chiqarish\n\nKompaniyani tanlang:",
        "invoice_select_amount": "Summani kiriting (USD, default ${default}):",
        "invoice_btn_default": "${price} ✓",
        "invoice_btn_custom": "O'z summam",
        "invoice_custom_prompt": "Summani USD da kiriting:",
        "invoice_sent": "✅ Hisob {company} kompaniyasiga yuborildi.",
        # Scheduled posts
        "scheduled_posts_empty": "📅 Rejalashtirilgan postlar yo'q.",
        "scheduled_posts_title": "📅 Rejalashtirilgan postlar ({count} ta):",
        "scheduled_post_cancelled": "✅ Rejalashtirilgan post bekor qilindi.",
        # Edit existing property
        "edit_prop_choose": "✏️ Qaysi maydonni o'zgartirmoqchisiz?",
        "edit_prop_updated": "✅ Yangilandi!",
        "edit_prop_type_select": "Yangi turni tanlang:",
        # Developer commands
        "new_company_prompt_name": "🏢 Yangi kompaniya nomini kiriting:",
        "new_company_prompt_channel": "Telegram kanal ID kiriting:\nMisol: @my_channel yoki -1001234567890\n\n/skip — keyinroq",
        "new_company_created": "✅ Kompaniya yaratildi!\nNomi: {name}\nID: {id}",
        "set_role_usage": "Foydalanish:\n/set_role <tg_id> <rol> [company_id]\n\nRollar: agent, director, client, developer",
        "set_role_done": "✅ Foydalanuvchi yangilandi\nTG ID: {tg_id}\nRol: {role}",
        # AI consultation
        "btn_ai_consult": "🤖 Konsultatsiya",
        "btn_ask_ai": "🤖 Savol berish (AI)",
        "ai_consult_intro": (
            "🤖 <b>AI-konsultant</b>\n\n"
            "Sizga qanday ko'chmas mulk kerakligi haqida gapirib bering.\n"
            "Men sizga mos variantlarni topishda yordam beraman.\n\n"
            "❌ Chiqish uchun /stop yozing."
        ),
        "ai_limit_reached": "⚠️ Bugungi AI so'rovlar limitiga yetdingiz. Ertaga urinib ko'ring.",
        # Client alerts
        "btn_notify_alert": "🔔 Yangi chiqsa, xabar bering",
        "alert_subscribed": "🔔 Obuna faollashtirildi! Yangi mos obyekt chiqsa xabar beramiz.",
        "alert_unsubscribed": "🔕 Barcha bildirishnomalar o'chirildi.",
        # Director profile & balance
        "btn_profile": "👤 Mening profilim",
        "btn_topup_balance": "💳 Balansni to'ldirish",
        "btn_balance_history": "📜 Tranzaksiyalar tarixi",
        "btn_dashboard": "📊 To'liq statistika (Dashboard)",
        "dev_new_topup": "💰 <b>Yangi balans to'ldirish</b>\n\nKompaniya: {company}\nDirektor: {name}\nSumma: ${amount}\nUsul: {method}",
        # Add property — new step-by-step FSM
        "ap_step_type":     "🏠 Mulk turini tanlang:",
        "ap_step_district": "📍 Tumanni tanlang:",
        "ap_enter_district": "Tuman nomini kiriting:\n(Misol: Mirzo Ulug'bek)",
        "ap_step_address":  "🏠 Aniq manzilni kiriting:\n(Ko'cha, uy raqami)\n\n<i>Ixtiyoriy — o'tkazib yuborish mumkin</i>",
        "ap_step_rooms":    "🚪 Necha xonali uy kerak?",
        "ap_step_floor":    "🏢 Qavat raqamini kiriting:\n\n<i>Ixtiyoriy — /skip yozing</i>",
        "ap_step_total_floors": "🏢 Jami qavatlar sonini kiriting:\n\n<i>Ixtiyoriy — /skip yozing</i>",
        "ap_step_area":     "📐 Maydonni tanlang (m²):",
        "ap_enter_area":    "📐 Maydonni m² da kiriting (raqam):\nMisol: 75",
        "ap_step_price":    "💰 Narxni tanlang (USD):",
        "ap_enter_price":   "💰 Narxni USD da kiriting (faqat raqam):\nMisol: 65000",
        "ap_step_features": (
            "✨ <b>Qo'shimcha xususiyatlar</b>\n\n"
            "Mavjud xususiyatlarni tanlang (bir nechtasini).\n"
            "Tanlash/bekor qilish uchun tugmani bosing.\n\n"
            "Tayyor bo'lgach \"Tayyor\" tugmasini bosing."
        ),
        "ap_step_keywords": (
            "💬 Qo'shimcha ma'lumot kiriting:\n"
            "<i>(masalan: yangi qurilgan, metro yaqin, ta'mir kerak)</i>\n\n"
            "Ixtiyoriy — o'tkazib yuborish mumkin."
        ),
        "ap_step_media": (
            "📸 <b>Rasm va videolarni yuklang</b>\n\n"
            "• Kamida 1 ta rasm (maksimal 10)\n"
            "• Video ixtiyoriy (maksimal 2)\n\n"
            "Hammasi tayyor bo'lgach \"Tayyor\" tugmasini bosing."
        ),
        "ap_media_received":    "📸 {count} ta rasm qabul qilindi.",
        "ap_video_received":    "📹 {count} ta video qabul qilindi.",
        "ap_media_limit_photo": "❌ Maksimal 10 ta rasm. Tayyor tugmasini bosing.",
        "ap_media_limit_video": "❌ Maksimal 2 ta video.",
        "ap_media_need_one":    "❌ Kamida 1 ta rasm yuboring.",
        "ap_processing":        "⏳ Ma'lumotlar tayyorlanmoqda...\nBir daqiqa kuting.",
        "ap_preview_header":    "📋 <b>Tekshirib ko'ring:</b>\n\n",
        "ap_desc_edit_prompt":  "✏️ Yangi tavsifni kiriting:",
        "ap_step_pub_date":     "📅 Qaysi kuni e'lon qilinsin?",
        "ap_step_pub_time":     "🕐 Soatni tanlang:",
        "ap_enter_pub_date":    "Sanani kiriting (format: DD.MM.YYYY):\nMisol: 25.06.2026",
        "ap_enter_pub_time":    "Vaqtni kiriting (format: HH:MM):\nMisol: 14:30",
        "ap_date_error":        "❌ Noto'g'ri format. Misol: 25.06.2026",
        "ap_time_error":        "❌ Noto'g'ri format. Misol: 14:30",
        "ap_scheduled_ok":      "⏰ {dt} da e'lon qilinishi rejalashtirildi.",
        "ap_saved_only":        "💾 Faqat bazaga saqlandi.",
        "ap_cancelled":         "❌ Bekor qilindi.",
        "ap_price_error":       "❌ Raqam kiriting. Misol: 65000",
        "ap_rooms_error":       "❌ Raqam kiriting.",
        "ap_floor_error":       "❌ Raqam kiriting yoki /skip yozing.",
        # Follow-up messages
        "follow_up_day3": (
            "Salom, {name}! 👋\n\n"
            "3 kun oldin siz {district} tumanida uy qidiruvda edingiz.\n"
            "Yangi variantlar paydo bo'ldi! Ko'rasizmi?"
        ),
        "follow_up_day7": (
            "{name}, esingizdami? 🏠\n\n"
            "Sizga yoqishi mumkin bo'lgan ${budget} dagi yangi variantlar bor."
        ),
        "follow_up_day14": (
            "{name}, oxirgi marta yozaman 😊\n\n"
            "Agar uy hali kerak bo'lsa — biz tayyor.\n"
            "Yo'q bo'lsa — sizga omad tilaymiz!"
        ),
        "btn_follow_up_yes": "✅ Ha, ko'rsating",
        "btn_follow_up_no": "❌ Hozir kerak emas",
        "btn_follow_up_unsub": "🔕 Bunday bildirishnomalarni yopish",
        "btn_follow_up_looking": "Hali izlayman",
        "btn_follow_up_found": "Topdim, rahmat",
        # Channel post format
        "channel_post": (
            "{type_icon} <b>{prop_type} | {district}</b>\n\n"
            "💰 <b>${price_usd}</b> (~{price_uzs:,} so'm)\n"
            "🚪 {rooms} xona  •  {floor_info}  •  📐 {area} m²\n"
            "{address_line}"
            "\n{features_line}"
            "{description}"
            "📞 <b>Aloqa:</b> {agent_phone}\n"
            "👤 Agent: {agent_username}\n\n"
            "{hashtags}"
        ),
    }
}


def t(key: str, lang: str = "uz", **kwargs) -> str:
    text = TEXTS.get(lang, TEXTS["uz"]).get(key, f"[{key}]")
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, ValueError):
            return text
    return text
