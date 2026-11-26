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

Without Moodle, CampusPilot still answers questions about official pages. With it, you can ask about your deadlines and courses. Use one of these:

- In Moodle go to **Preferences** -> **Security keys** and copy the **Moodle mobile web service** key. Paste it in Settings.
- Or go to **Calendar** -> **Export calendar** and copy the calendar URL. Paste it in Settings.

If your Moodle cannot be reached from the hosted version, CampusPilot says so. The local app can still do it.

## What is stored, and what is sent

| | Where it goes |
|---|---|
| Your AI key | Stays in your browser. It is sent with each request and used once. The server does not store it. |
| Your Moodle key or calendar URL | Stays in your browser. It is sent only to reach IITB Moodle, and the server does not store it. |
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
