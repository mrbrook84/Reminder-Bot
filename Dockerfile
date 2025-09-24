# Base image အဖြစ် Python 3.10-slim ကိုအသုံးပြုပါမယ်။
# slim version က image size သေးငယ်စေပါတယ်။
FROM python:3.10-slim

# Container ထဲမှာ အလုပ်လုပ်မယ့် Directory ကို /app လို့သတ်မှတ်ပါမယ်။
WORKDIR /app

# ပထမဆုံး requirements.txt ကိုအရင်ကူးထည့်ပါမယ်။
# ဒါမှနောက်ပိုင်း code ပြင်တဲ့အခါတိုင်း dependency တွေကိုပြန်ပြန် install လုပ်နေမှာမဟုတ်တော့ပါဘူး။
COPY requirements.txt .

# requirements.txt ထဲမှာပါတဲ့ library တွေကို install လုပ်ပါမယ်။
RUN pip install --no-cache-dir -r requirements.txt

# ကျန်တဲ့ project file တွေအားလုံးကို container ထဲက /app directory ထဲကိုကူးထည့်ပါမယ်။
COPY . .

# သင့် bot ဟာ webhook mode မှာ run တဲ့အခါ port 8000 ကိုအသုံးပြုမှာဖြစ်တဲ့အတွက်
# ဒီ port ကို container ကနေ expose လုပ်ထားကြောင်း ကြေညာပါမယ်။
EXPOSE 8000

# Container ကို run လိုက်တဲ့အခါ "python bot.py" ဆိုတဲ့ command ကိုအလုပ်လုပ်စေပါမယ်။
# ဒီ command က သင့်ရဲ့ Procfile ထဲက web: python bot.py ကနေရယူထားတာဖြစ်ပါတယ်။ [cite: 2]
CMD ["python", "bot.py"]
