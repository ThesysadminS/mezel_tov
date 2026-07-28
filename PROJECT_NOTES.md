# סיכום פרויקט Wedding RSVP — מה עשינו ולמה

מסמך זה נועד בשבילך, כדי שתוכל לחזור ולהיזכר בלי לאבד את החוט. תעדכן אותו ככל שנתקדם.

---

## מה הפרויקט בכלל

אתר RSVP לחתונות. שני חלקים עיקריים:
- **דף ניהול** (`/admin`) — יוצרים "אירוע" חדש (זוג, תאריך, אולם)
- **דף אורח** (`/c/<couple_id>`) — כל זוג מקבל דף משלו, אורחים ממלאים אישור הגעה שם

**המחסנית (Stack):**
- Flask (Python) — הבק-אנד, בקובץ `app.py`
- HTML templates — `templates/admin.html`, `templates/index.html`
- בגרסה **האמיתית** (עתידית): AWS DynamoDB לאחסון + AWS Cognito ל-login
- Docker — לאריזת האפליקציה כך שתרוץ באותה צורה בכל מקום

---

## שני קבצי `app.py` — ואיך לא להתבלבל ביניהם

| קובץ | מה יש בו | מתי משתמשים |
|---|---|---|
| `app.py` (הגרסה שאנחנו עובדים איתה עכשיו) | **בלי** AWS/Cognito. שומר נתונים ב-`dev_data.json` מקומי. Login מדומה — נכנסים ישר בלי סיסמה. | פיתוח מקומי, לימוד, בדיקות |
| `app_aws_original.py` | הגרסה **האמיתית**, עם `boto3`, DynamoDB, Cognito | כשנחבר AWS אמיתי בעתיד |

⚠️ **תמיד תוודא באיזה `app.py` אתה עובד** — הכי קל: `head -20 app.py`. אם רואים `import boto3` זה הגרסה האמיתית; אם רואים docstring "`app_dev.py — גרסת פיתוח מקומית`" זה הגרסה שלנו.

---

## מבנה התיקייה שלך

```
wedding-rsvp/
├── app.py                    ← הגרסה בלי AWS (מה שרץ עכשיו)
├── app_aws_original.py       ← הגרסה האמיתית עם AWS, לעתיד
├── requirements.txt
├── Dockerfile
├── dev_data.json             ← נוצר אוטומטית, פה "המסד נתונים" המדומה שלנו
├── templates/
│   ├── admin.html
│   └── index.html
└── static/                   ← ריקה כרגע, אבל חייבת להתקיים בשביל Docker build
```

---

## מושגי קוד שעברנו (ב-`app.py`)

- **`import`** — מביא כלים מוכנים (ספריות) לתוך הקובץ
- **`f-string`** (`f"{x}-{y}"`) — דרך לשלב משתנים בתוך טקסט
- **`.strip()` / `.lower()`** — ניקוי טקסט (רווחים מיותרים / אותיות קטנות)
- **`re.sub(תבנית, החלפה, טקסט)`** — regex, מחפש-ומחליף לפי דפוס
- **`dict` (מילון)** — אוסף של `מפתח: ערך` (למשל `couple_id: פרטי הזוג`)
- **`list` (רשימה)** — אוסף מסודר של פריטים, עם סדר
- **`.get(key, default)`** — שולף ערך ממילון, בלי לקרוס אם המפתח לא קיים
- **List comprehension** (`[x for x in y if ...]`) — דרך קצרה לכתוב לולאה שבונה רשימה
- **Decorator** (`@login_required`, `@app.route(...)`) — "עוטף" פונקציה בהתנהגות נוספת, בלי לשכפל קוד
- **`@app.route("/c/<couple_id>")`** — נתיב דינמי; מה שכתוב אחרי `/c/` נתפס אוטומטית כפרמטר
- **GET מול POST** — GET = "תן לי מידע", POST = "הנה מידע, תעשה איתו משהו"
- **קודי סטטוס HTTP** — 200 (הצלחה), 400 (בקשה שגויה מהלקוח), 404 (לא נמצא), 500 (שגיאת שרת)
- **`io.StringIO` / `io.BytesIO`** — "קובץ מדומה" בזיכרון, בלי לשמור קובץ אמיתי בדיסק
- **`jsonify(...)`** — הופך מילון פייתון לתשובת JSON תקנית

### 🐛 באג ידוע שזיהינו (עדיין לא תוקן)
בפונקציה `create_couple`, השדה:
```python
"created_at": str(uuid.uuid4())
```
זה **UUID אקראי**, לא תאריך אמיתי! לכן המיון ב-`/admin` (מהחדש לישן) בעצם לא עובד נכון — הוא ממיין לפי משהו אקראי. **פתרון עתידי:** להחליף ל-
```python
from datetime import datetime, timezone
"created_at": datetime.now(timezone.utc).isoformat()
```
**עדיין לא תיקנו את זה בפועל — משימה פתוחה.**

---

## מושגי DevOps / Docker שעברנו

### פורטים
- פורט = "דלת" ממוספרת שדרכה תוכנית מקשיבה לבקשות רשת
- פורט 80 = ברירת המחדל של HTTP (זו הסיבה שלא צריך לכתוב `:80` בכתובת)
- פורטים מתחת ל-1024 דורשים `sudo` בלינוקס
- `0.0.0.0` = "תקשיב מכל כתובת" (גם ממחשבים אחרים ברשת), לעומת `127.0.0.1`/`localhost` = "רק מהמחשב הזה"

### Docker — למה בכלל
פותר את בעיית "עבד אצלי במחשב" — אורז את כל הסביבה (מערכת הפעלה מינימלית + Python + ספריות + קוד) לחבילה סגורה שרצה אותו דבר בכל מקום.

### מושגי יסוד
| מושג | הסבר |
|---|---|
| **Dockerfile** | "מתכון" בטקסט — הוראות בנייה |
| **Image** | התוצר הבנוי מהמתכון — קפוא, קריא-בלבד |
| **Container** | image שרץ בפועל |
| **Registry** | "מחסן" לאחסון images (Docker Hub, AWS ECR) |

זרימה: `Dockerfile --(docker build)--> Image --(docker run)--> Container רץ`

### VM מול Container
VM = מערכת הפעלה מלאה נפרדת (כבד, איטי לעלות). Container = חולק kernel עם המחשב המארח, רק מבודד ברמת תהליך (קליל, מהיר).

### Dockerfile שלנו, שורה-שורה

```dockerfile
FROM python:3.13-slim       # image בסיס, גרסת "slim" = קליל יותר
WORKDIR /app                 # תיקיית עבודה בתוך ה-image
COPY requirements.txt .      # מעתיקים קודם רק את זה (ר' Layer Caching למטה!)
RUN pip install --no-cache-dir -r requirements.txt   # מתקין ספריות, בזמן build
COPY app.py .                 # רק עכשיו מעתיקים את הקוד עצמו
COPY templates/ ./templates/
COPY static/    ./static/     # התיקייה חייבת להתקיים, גם ריקה!
EXPOSE 5000                   # תיעוד בלבד — לא באמת פותח גישה
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "app:app"]  # מה שרץ כשמפעילים container
```

### Layer Caching (מטמון שכבות) — הכלל הזהב
Docker בונה image בשכבות. כל שורה = שכבה. אם שכבה לא השתנתה מהפעם הקודמת — Docker משתמש בגרסה השמורה (מהיר!). ברגע ששכבה **כן** משתנה, **כל השכבות אחריה** נבנות מחדש גם הן.

**לכן:** דברים שמשתנים לעיתים רחוקות (`requirements.txt`) → למעלה בקובץ. דברים שמשתנים הרבה (הקוד שלך) → למטה. כך `pip install` הכבד לא רץ מחדש בכל שינוי קוד קטן.

### `RUN` מול `CMD`
| | `RUN` | `CMD` |
|---|---|---|
| מתי רץ | בזמן `docker build` | בזמן `docker run` |
| כמה אפשר | הרבה (כל אחד = שכבה) | רק אחד אחרון נחשב |
| נשמר ב-image? | כן, לצמיתות | לא, רק "הוראה מה להריץ" |

### gunicorn — למה לא `python app.py`
- `app.run()` הרגיל של Flask הוא **dev server** — חד-תהליכי, מטפל בבקשה אחת בכל רגע, לא עמיד לקריסות
- **gunicorn** מריץ כמה workers במקביל, מטפל בהרבה בקשות בו-זמנית, ומפעיל worker חדש אוטומטית אם אחד קורס
- לכן ה-`CMD` בDockerfile משתמש ב-gunicorn, לא ב-`python app.py`
- `"app:app"` = "בקובץ app.py, יש משתנה בשם app" (`app = Flask(__name__)`)

### פקודות שהרצנו בפועל

```bash
# בניית ה-image
docker build -t wedding-rsvp .

# הרצת container ברקע, עם מיפוי פורטים
docker run -d -p 8080:5000 --name wedding-rsvp-container wedding-rsvp

# רשימת images קיימים
docker images
```

- `-t wedding-rsvp` — שם קריא ל-image
- `.` — "תסתכל בתיקייה הנוכחית" (build context)
- `-d` — detached, רץ ברקע
- `-p 8080:5000` — `פורט_על_המחשב:פורט_בתוך_הקונטיינר`. זה מה **שבאמת** פותח גישה (בניגוד ל-`EXPOSE` שהוא רק תיעוד)
- `--name` — שם קריא לקונטיינר

**תוצאה:** האתר נגיש עכשיו ב-`http://localhost:8080/admin` — רץ בתוך container, לא ישירות דרך `python app.py`.

---

## איפה אנחנו עומדים עכשיו

✅ אפליקציה רצה מקומית עם Python ישירות
✅ אפליקציה רצה בתוך Docker container
⬜ תיקון הבאג של `created_at`
⬜ חיבור ל-DynamoDB אמיתי (או local)
⬜ חיבור ל-Cognito אמיתי
⬜ פריסה לענן (deployment)
⬜ CI/CD

---

## פקודות שימושיות לזכור

```bash
docker ps                              # אילו קונטיינרים רצים עכשיו
docker logs wedding-rsvp-container     # לוגים של הקונטיינר
docker stop wedding-rsvp-container     # לעצור
docker start wedding-rsvp-container    # להפעיל שוב (בלי לבנות מחדש)
docker rm wedding-rsvp-container       # למחוק קונטיינר (חייב לעצור קודם)
docker build -t wedding-rsvp .         # לבנות מחדש אחרי שינוי קוד
```
