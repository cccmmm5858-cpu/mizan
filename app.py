import os
import json
import re
from flask import Flask, request, jsonify, send_from_directory
import anthropic

app = Flask(__name__, static_folder='static')

# ══ تحميل قواعد البيانات ══════════════════════════════════════
with open('articles_database.json', encoding='utf-8') as f:
    CIVIL_RAW = json.load(f)

with open('ethbat_parsed.json', encoding='utf-8') as f:
    ETHBAT_RAW = json.load(f)

# تحويل للشكل الموحد: [title, content, source]
CIVIL_DB = [[a['article_title'], a['content'], 'civil'] for a in CIVIL_RAW]
ETHBAT_DB = [[a['title'], a['content'], 'ethbat'] for a in ETHBAT_RAW]
ALL_DB = CIVIL_DB + ETHBAT_DB

print(f"✓ محمّل: {len(CIVIL_DB)} مادة مدنية + {len(ETHBAT_DB)} مادة إثبات")

# ══ فهرس الكلمات المفتاحية ═══════════════════════════════════
CIVIL_IDX = {
    "قرض":      [385,386,387,388,389,390,391,392],
    "مقترض":    [385,386,387,388,390,391,392],
    "سلفة":     [385,386,391],
    "دين":      [148,207,208,209,222,225,228,229],
    "مديون":    [172,206,207,208,229],
    "كفالة":    [306,307,308,309,310,311,312,313],
    "كفيل":     [306,307,308,309,311,312,313],
    "وفاء":     [94,95,146,147,148,168,169,171,172],
    "مطل":      [27,169,171,172,173,174,229],
    "تعويض":    [107,111,120,121,122,123,124,125,126],
    "ضرر":      [26,27,120,121,122,123,124,125,126],
    "فسخ":      [106,107,108,109,110,111,112,113],
    "بطلان":    [38,48,49,74,75,76,77,80,81],
    "حوالة":    [239,240,241,242,243,244,245,246],
    "إعسار":    [196,197,205,206,230,235],
    "تقادم":    [296,297,298,299,300,301,302,303],
    "عقد":      [29,30,31,74,75,94,95],
    "التزام":   [29,94,95,106,107,171,172],
    "رسملة":    [94,95,107,172,173],
    "فائدة":    [94,95,285,286],
    "ربح":      [385,386,387,388,389,390,391],
    "تمويل":    [29,30,31,94,95,385,386],
    "عقار":     [22,308,309,310],
}

ETHBAT_IDX = {
    "إقرار":        [3,4,5,6,7,8,9,10,11],
    "شهادة":        [20,21,22,23,24,25,26,27,28],
    "شاهد":         [20,21,22,23,24,25,26,27,28],
    "دليل رقمي":    [17,18,19,20,21],
    "واتساب":       [17,18,19],
    "رسائل":        [14,17,18,19],
    "تحويل بنكي":   [17,18,19,20,21],
    "يمين":         [29,30,31,32,33],
    "كتابة":        [4,11,12,13,14,15,23,24,25],
    "محرر":         [12,13,14,15,16,17,18],
    "خبير":         [34],
    "تزوير":        [22,23,24,25,26],
    "مستند":        [12,13,14,15,16,17,18,19],
    "وثيقة":        [12,13,14,15,16],
    "كشف":          [17,18,19,20],
}

DIALECT_MAP = {
    "استلف": "قرض", "استلفت": "قرض", "سلفته": "سلفة",
    "ماطل": "مطل", "يماطل": "مطل", "ما سدد": "وفاء",
    "ضامن": "كفالة", "كفله": "كفالة",
    "واتساب": "واتساب", "تحويل": "تحويل بنكي",
    "خسرت": "تعويض", "خسارة": "تعويض",
    "مرابحة": "تمويل", "تورق": "تمويل", "تواروق": "تمويل",
    "رسمله": "رسملة", "رسّمل": "رسملة",
    "فجوه": "فجوة", "فرق": "تعويض",
}


def search_articles(query, top_k=8):
    """RAG: استرجاع المواد الأكثر صلة"""
    if not query or len(query.strip()) < 2:
        return []

    scores = {}

    # تطبيع اللهجة
    nq = query
    for d, l in DIALECT_MAP.items():
        if d in query:
            nq += " " + l

    words = [w for w in re.split(r'[\s،,\.؟?!]+', nq) if len(w) >= 2]

    # بحث بالكلمات المفتاحية في المعاملات المدنية (+3)
    for kw, indices in CIVIL_IDX.items():
        if any(kw in w or w in kw for w in words) or kw in nq:
            for i in indices:
                key = f"c{i}"
                scores[key] = scores.get(key, 0) + 3

    # بحث في الإثبات (+4)
    for kw, indices in ETHBAT_IDX.items():
        if any(kw in w or w in kw for w in words) or kw in nq:
            for i in indices:
                key = f"e{i}"
                scores[key] = scores.get(key, 0) + 4

    # بحث نصي مباشر (+1)
    tokens = [w for w in words if len(w) >= 3]
    for i, art in enumerate(CIVIL_DB):
        hits = sum(1 for t in tokens if t in art[1])
        if hits:
            scores[f"c{i}"] = scores.get(f"c{i}", 0) + hits

    for i, art in enumerate(ETHBAT_DB):
        hits = sum(1 for t in tokens if t in art[1])
        if hits:
            scores[f"e{i}"] = scores.get(f"e{i}", 0) + hits

    # ترتيب وإرجاع أفضل top_k
    sorted_keys = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:top_k]
    results = []
    for key, score in sorted_keys:
        is_e = key[0] == 'e'
        idx = int(key[1:])
        db = ETHBAT_DB if is_e else CIVIL_DB
        if idx < len(db) and len(db[idx][1]) > 20:
            results.append({
                'title': db[idx][0],
                'content': db[idx][1],
                'source': 'ethbat' if is_e else 'civil',
                'score': score
            })
    return results


def build_prompt(base_prompt, query):
    """بناء System Prompt مع حقن المواد"""
    found = search_articles(query, 8)
    if not found:
        return base_prompt

    ctx_parts = []
    for a in found:
        src = "[نظام الإثبات م/43]" if a['source'] == 'ethbat' else "[نظام المعاملات المدنية م/191]"
        ctx_parts.append(f"{src} 【{a['title']}】\n\"{a['content']}\"")

    ctx = "\n\n---\n\n".join(ctx_parts)

    return base_prompt + f"""

══════════════════════════════════════════════════════
## المواد القانونية المُسترجعة من قاعدة البيانات الرسمية
## (مصدر: نظام المعاملات المدنية م/191 + نظام الإثبات م/43 لعام 1443هـ)
══════════════════════════════════════════════════════

{ctx}

══════════════════════════════════════════════════════
تعليمات إلزامية:
1. لا تستشهد إلا بالمواد الواردة أعلاه مع ذكر مصدرها.
2. اعرض كل مادة: [المصدر] 【اسم المادة】 ثم النص الصريح ثم وجه الاستدلال.
3. إذا لم تجد نصاً صريحاً: "يُرجع إلى القواعد العامة وفق المادة الأولى."
══════════════════════════════════════════════════════"""


FINANCIAL_BASE = """أنت "ميزان" — محرك الذكاء الاصطناعي القانوني المتخصص في المطالبات المالية أمام المحاكم السعودية.
مزوَّد بـ 860 مادة: نظام المعاملات المدنية م/191 لعام 1443هـ (731 مادة) + نظام الإثبات م/43 لعام 1443هـ (129 مادة).

## مرحلة الاستخلاص:
استخرج من أي قصة أو مستند مرفق: المبالغ، التواريخ، طبيعة العقد، الأدلة، هوية الأطراف.
إذا رُفع ملف أو صورة: استخرج منها البيانات القانونية وادمجها في تحليلك.

## تقييم القضية (0-100):
تحويل بنكي: +40 | سند موقع: +35 | واتساب/رسائل: +30 | إقرار صريح: +45 | شاهدان: +20

## الأسئلة التكيفية (عند نقص الأدلة):
1. هل يوجد تحويل بنكي؟ (المادة 53 إثبات)
2. هل يوجد رسائل واتساب؟ (المادة 53 إثبات)
3. هل يوجد شهود بالغون؟ (المادة 65 إثبات)
4. هل أقرّ الطرف الآخر بالمبلغ؟ (المادة 14 إثبات)

## صياغة اللائحة:
ابدأ: "تفيد الدائرة الموقرة بأن المدعي..."
اختتم: "لذا يلتمس المدعي من الدائرة الموقرة الحكم بما يلي..."

## عرض المواد (إلزامي):
【اسم المادة كاملاً】
"النص الصريح للمادة"
وجه الاستدلال: كيف تنطبق على القضية"""

PERSONAL_BASE = """أنت "ميزان" — محرك الذكاء الاصطناعي القانوني لقضايا الأحوال الشخصية أمام المحاكم السعودية.
مزوَّد بنظام المعاملات المدنية م/191 ونظام الإثبات م/43 كمرجعين أساسيين.

## استخراج البيانات:
نوع القضية (نفقة/حضانة/زيارة/طلاق)، أعمار الأطفال، مدة الانقطاع، الأدلة.
إذا رُفع مستند: استخرج منه البيانات.

## تقييم القضية (0-100):
عقد زواج: +35 | شهادة ميلاد: +25 | إثبات انقطاع: +20 | حكم سابق: +15

## الأسلوب:
"تفيد الدائرة الموقرة..." / "استناداً لأحكام الشريعة الإسلامية..." """


# ══ API Routes ═══════════════════════════════════════════════

@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

@app.route('/static/<path:filename>')
def static_files(filename):
    return send_from_directory('static', filename)


@app.route('/api/chat', methods=['POST'])
def chat():
    try:
        data = request.json
        messages = data.get('messages', [])
        case_type = data.get('case_type', 'financial')
        query = data.get('query', '')

        if not messages:
            return jsonify({'error': 'لا توجد رسائل'}), 400

        # بناء System Prompt ديناميكي
        base = FINANCIAL_BASE if case_type == 'financial' else PERSONAL_BASE
        system = build_prompt(base, query)

        # استدعاء Anthropic API
        client = anthropic.Anthropic(api_key=os.environ.get('ANTHROPIC_API_KEY'))
        response = client.messages.create(
            model="claude-sonnet-4-5-20251001",
            max_tokens=2000,
            system=system,
            messages=messages
        )

        reply = response.content[0].text

        # إرجاع الرد مع المواد المُسترجعة
        retrieved = search_articles(query, 8)

        return jsonify({
            'reply': reply,
            'retrieved_articles': retrieved
        })

    except anthropic.AuthenticationError:
        return jsonify({'error': 'مفتاح API غير صحيح'}), 401
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/search', methods=['POST'])
def search():
    """بحث في قاعدة البيانات"""
    data = request.json
    query = data.get('query', '')
    results = search_articles(query, 8)
    return jsonify({'results': results})


@app.route('/api/articles', methods=['GET'])
def get_articles():
    """جلب المواد للتصفح"""
    page = int(request.args.get('page', 0))
    per_page = int(request.args.get('per_page', 12))
    source = request.args.get('source', 'all')
    query = request.args.get('q', '')

    if source == 'civil':
        db = CIVIL_DB
    elif source == 'ethbat':
        db = ETHBAT_DB
    else:
        db = ALL_DB

    if query:
        db = [a for a in db if query in a[0] or query in a[1]]

    total = len(db)
    items = db[page * per_page:(page + 1) * per_page]

    return jsonify({
        'total': total,
        'page': page,
        'items': [{'title': a[0], 'content': a[1], 'source': a[2]} for a in items]
    })


@app.route('/health')
def health():
    return jsonify({
        'status': 'ok',
        'civil_articles': len(CIVIL_DB),
        'ethbat_articles': len(ETHBAT_DB),
        'total': len(ALL_DB)
    })


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
