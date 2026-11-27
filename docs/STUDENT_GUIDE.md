# CampusPilot: student guide

CampusPilot is an **unofficial prototype**. It is not made or endorsed by IIT Bombay. It answers questions using official IITB pages it has indexed, shows where each answer came from, and can show your Moodle deadlines. It can be wrong. Check the linked official page before you act on anything important.

## You need your own AI key (free)

CampusPilot has no AI account of its own. You bring a key, and the AI provider you choose answers your questions. Groq is free and needs no card.

1. Open https://console.groq.com and sign in.
2. Go to **API Keys** and click **Create API Key**.
3. Copy the key. Treat it like a password.
4. Open CampusPilot, choose **Groq**, paste the key and press **Test key**.

## Remember on this device

In Settings, each section has a **Remember on this device** switch.

- **Off (default):** your key is forgotten when you close the tab.
- **On:** your key stays in this browser until you remove it. Do not turn this on for a shared or public computer.

## Connect Moodle (optional)

Without Moodle, CampusPilot still answers questions about official pages. With it, you can ask about your deadlines.

In Moodle go to **Calendar** -> **Export calendar**, choose **All events** and **Recent and next 60 days**, then click **Get calendar URL**. Copy the link and paste it in Settings.

The link contains a private key, so treat it like a password: don't share it or post it anywhere. If it ever leaks, export a new one in Moodle.

If your Moodle cannot be reached from the hosted version, CampusPilot says so. The local app can still do it.

## Connectors (local app only)

Webmail, ASC and Google Calendar work only in the local app on your own computer. The hosted site never stores your mail, ASC or Google logins, so in Settings it shows these three as "Local app only" with a **How to connect** guide. Moodle works on the hosted site: paste your calendar link as above.

To get the local app:

1. Run `git clone https://github.com/biprabhanu/iitb-campus-assistant`, then `make setup` inside the folder.
2. In the `.env` file set the connector you want to `true`: `WEBMAIL_ENABLED=true`, `ASC_ENABLED=true` or `GCAL_ENABLED=true`.
3. Run `make dev`, open http://127.0.0.1:3000 and go to Settings, then Connectors.

Then, for each connector:

- **Webmail:** you need your IITB LDAP ID and an access token for Emails, not your LDAP password. Make the token at sso.iitb.ac.in: Manage account, Access tokens, Emails. It is saved in the macOS Keychain. CampusPilot only reads your mail (read-only, and it never marks mail as read); it never sends, moves or deletes anything. Mail is read only by the local model.
- **ASC:** you need your LDAP ID and LDAP password, and you must be on the campus network or the IITB VPN. ASC is a plain LDAP form (no OTP). CampusPilot reads your timetable, courses, registration and profile, and shows the "Scholarship month view (ASC)" (the ASC fees page has a month picker only, so there is no fee table; check dues on ASC). Your profile includes your academic standing. It never reads grades. Your own ASC data is shown only when the local Gemma model is selected; with a cloud model, CampusPilot refuses those questions and tells you to switch to Local Gemma. Public ASC data (running courses, offering history, course details) works with any model.
- **Google Calendar:** in the Google Cloud Console create an OAuth client of type "Desktop app" and save the downloaded file as `~/.campuspilot/google_client.json`. Then press **Connect Google Calendar**. An event is added only when you click **Add** on an event card, and never twice.

## What is stored, and what is sent

| | Where it goes |
|---|---|
| Your AI key | Stays in your browser. It is sent with each request and used once. The server does not store it. |
| Your Moodle calendar link | Stays in your browser. It is sent only to reach IITB Moodle, and the server does not store it. |
| Your Moodle content (deadlines, courses) | Shown to you only. **It is never sent to the AI provider.** |
| Your questions, and the excerpts of official pages used to answer | **Sent to the AI provider you chose** (for example Groq). Their privacy rules apply to that. |
| Anything else | The server stores nothing about you. |

Gemini's free tier may use your prompts to improve Google's products. Groq is recommended.

## Forget everything

Open Settings and press **Forget everything**. It removes your AI key and Moodle details from this browser. To also stop the key from working, delete it in your provider's dashboard.

## Messages you may see

| Message | What it means | What to do |
|---|---|---|
| Key rejected | The provider did not accept your key. It may be mistyped, deleted or for another provider. | Press **Change key**, paste it again, and use **Test key**. |
| Free limit | The provider says you used up your free allowance for now. | Wait a minute (it may say how long) and try again. |
| Waking the server | The free server sleeps when nobody uses it and takes about a minute to wake. | Wait. It retries by itself for about 90 seconds. |
| Moodle not available | The hosted server cannot reach Moodle. | Use CampusPilot's official-page answers, or run the local app. |
