# راهنمای راه‌اندازی — Ecosystem Radar

پروژه‌ای که ربات هر روز واقعاً رویش کار می‌کند:

- دادهٔ ۴۲ پروژهٔ متن‌باز را از GitHub API و PyPI می‌گیرد
- سری‌زمانی می‌سازد و شتاب رشد را حساب می‌کند
- تغییرات را با **Pull Request** وارد می‌کند، نه کامیت مستقیم
- برای یافته‌های واقعی **Issue** باز و بسته می‌کند

جمعه‌ها (به وقت تهران) کار نمی‌کند.

---

## اگر ریپو را قبلاً ساخته‌ای

فقط این فایل‌ها را به‌روز کن یا اضافه کن:

```
src/radar/alerts.py          ← جدید
src/radar/issues.py          ← جدید
src/radar/sources.py         ← عوض شده
src/radar/storage.py         ← عوض شده
scripts/collect.py           ← عوض شده
scripts/sync_issues.py       ← جدید
tests/test_alerts.py         ← جدید
tests/test_issues.py         ← جدید
.github/workflows/collect.yml ← عوض شده
README.md                    ← عوض شده
docs/METHODOLOGY.md          ← عوض شده
```

بعد برو گام ۳ (توکن).

---

## گام ۱ — ریپو

ریپوی **public**. Actions روی public نامحدود است و کارفرما می‌تواند ببیندش.

## گام ۲ — فایل‌ها

محتویات این پوشه را در ریشهٔ ریپو بریز.

پوشهٔ `.github` را نمی‌شود drag & drop کرد. باید
`Add file → Create new file` بزنی و در اسم فایل تایپ کنی
`.github/workflows/ci.yml` تا پوشه خودکار ساخته شود.

## گام ۳ — ایمیل (متغیر)

`Settings` ریپو → `Secrets and variables` → `Actions` → تب **Variables**
→ `New repository variable`

| Name | `GIT_EMAIL` |
|---|---|
| Value | `156174139+Amirzamani1l@users.noreply.github.com` |

بدون این، کامیت‌ها به اسم ربات ثبت می‌شوند و سبز نمی‌شوی.

## گام ۴ — توکن (Secret) — برای Issue و PR

این گام **جدید** است و بدون آن Issue و PR به اسم `github-actions[bot]`
ثبت می‌شوند، نه تو.

۱. برو `https://github.com/settings/personal-access-tokens`
۲. `Generate new token`
۳. پرش کن:

| فیلد | مقدار |
|---|---|
| Token name | `radar` |
| Expiration | ۱ سال |
| Repository access | **Only select repositories** → `oss-momentum` |

۴. بخش **Repository permissions**، این چهار تا را روی **Read and write**:

- `Contents`
- `Issues`
- `Pull requests`
- `Workflows`

۵. `Generate token` → کپی کن (فقط یک بار نشان می‌دهد)

۶. برگرد `Settings` ریپو → `Secrets and variables` → `Actions` →
   تب **Secrets** → `New repository secret`

| Name | `RADAR_TOKEN` |
|---|---|
| Secret | توکنی که کپی کردی |

> اگر این گام را رد کنی، بازی همچنان کار می‌کند — فقط Issue و PR به اسم
> ربات ثبت می‌شوند و روی نمودار تو نمی‌آیند.

## گام ۵ — اجازهٔ نوشتن

`Settings` → `Actions` → `General` → پایین، **Workflow permissions** →
**Read and write permissions** → `Save`

همان‌جا تیک **Allow GitHub Actions to create and approve pull requests**
را هم بزن.

## گام ۶ — اجرا

`Actions` → `Collect` → `Run workflow`

---

## چه انتظاری داشته باش

اجرای اول:

- یک **Pull Request** باز و merge می‌شود، با عنوانی مثل
  `data: 2026-08-23 snapshot (42 projects, +1,204 stars, polars leading)`
- `data/observations.csv` ساخته می‌شود
- README پر می‌شود
- احتمالاً چند **Issue** باز می‌شود (پروژه‌های راکد یا افت‌کرده)

اجراهای بعدی:

- اگر داده عوض شده باشد، PR جدید
- اگر شرطی برطرف شده باشد، Issue مربوطه با توضیح بسته می‌شود
- اگر هیچ تغییری نباشد، هیچ کاری نمی‌کند

---

## چک نهایی

| کجا | چه ببینی |
|---|---|
| تب Pull requests | یک PR بسته‌شده با آواتار **خودت** |
| تب Issues | چند Issue با آواتار **خودت** |
| تب Commits | کامیت `data: ...` با آواتار **خودت** |

اگر هر کدام `github-actions[bot]` بود، `RADAR_TOKEN` یا `GIT_EMAIL` غلط است.

---

## نکتهٔ مهم دربارهٔ Issue ها

سیستم فقط Issue هایی را دست می‌زند که **خودش** ساخته باشد. هر Issue
دارای یک نشانهٔ مخفی در متنش است (`<!-- radar:... -->`).

اگر خودت یا کس دیگری Issue باز کند، هیچ‌وقت بسته یا تغییر داده نمی‌شود.
این در تست‌ها تضمین شده.

---

## عیب‌یابی

| مشکل | راه‌حل |
|---|---|
| `Permission denied` هنگام push | گام ۵ |
| `GitHub Actions is not permitted to create pull requests` | گام ۵، تیک دوم |
| PR/Issue به اسم ربات | گام ۴ — `RADAR_TOKEN` |
| کامیت به اسم ربات | گام ۳ — `GIT_EMAIL` |
| `gh pr merge` خطا می‌دهد | branch protection روی main داری. `Settings → Branches` → بردارش |
| Issue تکراری باز می‌شود | نباید بشود؛ اگر شد یعنی متن Issue دستی ویرایش شده و نشانه پاک شده |
| نمودار ۳۰ روزه خالی | طبیعی، تا ۳۰ روز اول داده کافی نیست |

---

## اجرای محلی

```bash
pip install -r requirements-dev.txt

pytest                                    # ۱۸۱ تست
ruff check . && ruff format --check .

# سه پروژه، بدون نوشتن چیزی
GITHUB_TOKEN=توکنت python scripts/collect.py --dry-run --limit 3

# ببین چه Issue هایی باز می‌شد، بدون توکن
python scripts/sync_issues.py --dry-run
```

---

## تنظیم آستانه‌ها

بالای `src/radar/alerts.py`:

```python
STALLED_PUSH_DAYS = 45
SPIKE_Z = 2.5
SLUMP_GROWTH_PCT = 0.0
DROUGHT_DAYS = 180
UNREACHABLE_RUNS = 3
```

اگر Issue زیادی باز شد، این عددها را سخت‌گیرانه‌تر کن.

---

## یک نکتهٔ صادقانه

`docs/METHODOLOGY.md` را یک بار بخوان. ده دقیقه وقت می‌برد.

اگر کسی پرسید «چرا آستانهٔ spike را ۲.۵ گذاشتی نه ۲؟» جوابش آنجاست
(دم‌های چاق توزیع رشد ستاره). فرق بین «پروژهٔ من» و «پروژه‌ای که یکی
برایم ساخت» دقیقاً همین است.
