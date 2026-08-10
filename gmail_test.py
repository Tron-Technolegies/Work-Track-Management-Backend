import smtplib

EMAIL = "sanjukunju176@gmail.com"
APP_PASSWORD = "pcsg dcal sjoj bapz"   # Paste your NEW app password

try:
    server = smtplib.SMTP("smtp.gmail.com", 587)
    server.ehlo()
    server.starttls()
    server.ehlo()

    server.login(EMAIL, APP_PASSWORD)
    print("✅ Login Successful!")

    server.sendmail(
        EMAIL,
        EMAIL,
        "Subject: Test\n\nHello from Python!"
    )

    print("✅ Email Sent!")
    server.quit()

except Exception as e:
    print("❌", e)