import smtplib
from utils.encryption import decrypt_password

def send_email_notification(company, subject, message, recipient_email):

    password = decrypt_password(company.smtp_password).replace(" ", "")

    server = smtplib.SMTP(company.smtp_host, company.smtp_port)
    server.ehlo()
    server.starttls()
    server.ehlo()

    server.login(company.smtp_email, password)

    server.sendmail(
        company.smtp_email,
        recipient_email,
        f"Subject: {subject}\n\n{message}"
    )

    server.quit()