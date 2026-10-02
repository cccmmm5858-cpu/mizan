import hashlib
import os
from pathlib import Path

import anthropic
from flask import Flask, jsonify, request, send_from_directory
from werkzeug.exceptions import HTTPException

from foundations import (ARTICLES, RateLimiter, authenticated, build_prompt,
                         normalize, render_reply, search_articles, validate_chat)

ROOT = Path(__file__).resolve().parent
app = Flask(__name__, static_folder=str(ROOT / 'static'))
app.config.update(MAX_CONTENT_LENGTH=128 * 1024,
                  CHAT_ACCESS_TOKEN=os.environ.get('CHAT_ACCESS_TOKEN', ''),
                  RATE_LIMIT_DB=os.environ.get('RATE_LIMIT_DB', str(ROOT / 'instance' / 'rate-limit.sqlite3')),
                  CHAT_RATE_LIMIT=10, CHAT_RATE_WINDOW=60)


@app.after_request
def security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; base-uri 'self'"
    if request.path.startswith('/api/'):
        response.headers['Cache-Control'] = 'no-store'
    return response


@app.errorhandler(Exception)
def safe_error(error):
    if isinstance(error, HTTPException):
        return jsonify(error='تعذر معالجة الطلب؛ تحقق من البيانات وحجمها'), error.code
    # Do not log provider exception messages, request bodies, or credentials.
    app.logger.error('Request failed (%s)', type(error).__name__)
    return jsonify(error='تعذر إكمال الطلب حاليًا'), 500


@app.route('/')
def index():
    return send_from_directory(app.static_folder, 'index.html')


@app.route('/api/chat', methods=['POST'])
def chat():
    token = app.config['CHAT_ACCESS_TOKEN']
    if not authenticated(request.headers.get('Authorization'), token):
        return jsonify(error='يلزم رمز وصول صالح لاستخدام المحادثة'), 401
    try:
        path = Path(app.config['RATE_LIMIT_DB'])
        path.parent.mkdir(parents=True, exist_ok=True)
        limiter = RateLimiter(path, app.config['CHAT_RATE_LIMIT'], app.config['CHAT_RATE_WINDOW'])
        # Shared credential has a single budget: changing IP/forwarded headers cannot bypass it.
        if not limiter.allow(hashlib.sha256(token.encode()).hexdigest()):
            response = jsonify(error='تم بلوغ حد الطلبات؛ حاول لاحقًا')
            response.headers['Retry-After'] = str(app.config['CHAT_RATE_WINDOW'])
            return response, 429
        try:
            messages, query = validate_chat(request.get_json(silent=True))
        except ValueError as error:
            return jsonify(error=str(error)), 400
        found = search_articles(query)
        if not found:
            return jsonify(reply='لم أجد نصوصًا مناسبة في قاعدة البيانات؛ يرجى توضيح الوقائع.', retrieved_articles=[])
        # No API key is exposed to the browser. No provider retries that multiply costs.
        client = anthropic.Anthropic(api_key=os.environ.get('ANTHROPIC_API_KEY'), timeout=30, max_retries=0)
        response = client.messages.create(model='claude-sonnet-4-5', max_tokens=600,
                                          system=build_prompt(found), messages=messages)
        raw = ''.join(block.text for block in response.content if getattr(block, 'type', None) == 'text')
        reply = render_reply(raw, found)
        return jsonify(reply=reply, retrieved_articles=found)
    except HTTPException:
        raise
    except Exception as error:
        app.logger.error('Chat failed (%s)', type(error).__name__)
        return jsonify(error='تعذر إكمال الطلب حاليًا؛ حاول لاحقًا'), 503


@app.route('/api/search', methods=['POST'])
def search():
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or not isinstance(data.get('query'), str) or len(data['query']) > 6000:
        return jsonify(error='أرسل نص بحث صالحًا'), 400
    return jsonify(results=search_articles(data['query']))


@app.route('/api/articles')
def get_articles():
    try:
        page = int(request.args.get('page', 0))
        per_page = int(request.args.get('per_page', 12))
        if page < 0 or not 1 <= per_page <= 100:
            raise ValueError
    except ValueError:
        return jsonify(error='قيم الصفحة غير صالحة'), 400
    source = request.args.get('source', 'all')
    if source not in {'civil', 'ethbat', 'all'}:
        return jsonify(error='المصدر غير صالح'), 400
    query = normalize(request.args.get('q', ''))
    db = [a for a in ARTICLES if (source == 'all' or a['source'] == source)
          and (not query or query in normalize(a['title'] + ' ' + a['content']))]
    return jsonify(total=len(db), page=page, items=db[page * per_page:(page + 1) * per_page])


@app.route('/health')
def health():
    return jsonify(status='ok', civil_articles=sum(a['source'] == 'civil' for a in ARTICLES),
                   ethbat_articles=sum(a['source'] == 'ethbat' for a in ARTICLES), total=len(ARTICLES))


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=False)
