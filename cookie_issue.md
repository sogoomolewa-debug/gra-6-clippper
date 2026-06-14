# YouTube Bot-Detection & Cookie Invalidation Guide

This document explains why YouTube blocks automated downloads (the `"Sign in to confirm you're not a bot"` error), how session cookies are rotated, and the mitigation strategies to keep the **GTA6 Shorts Pipeline** running reliably in production.

---

## 🔍 The Root Cause: YouTube's Anti-Bot Shield

YouTube employs sophisticated, multi-layered security measures to block automated scrapers, downloaders, and botnets. The platform uses three primary indicators to determine if a connection is a bot:

### 1. IP Address Reputation (Data Center Flags)
When the pipeline runs inside **GitHub Actions** or **GitHub Codespaces**, the outbound requests originate from **Microsoft Azure / AWS IP ranges**. YouTube flags these data center IP ranges as high-risk. Anonymous (non-logged-in) requests from these IPs are almost instantly blocked with a `403 Forbidden` or a captcha requirement.

### 2. Session Cookie Fingerprinting & Rotation
Passing Netscape cookies tells YouTube: *"I am a legitimate, logged-in user."* However, YouTube checks if the session footprint matches:
*   **User-Agent mismatch**: If your browser exported the cookies with a specific user-agent (e.g., Safari on macOS) but `yt-dlp` sends its default user-agent (Windows Chrome), Google flags the request as a session hijacking attempt and **instantly revokes the cookie session**.
*   **Location Jump**: A session suddenly moving from a home residential IP (where you logged in) to an Azure data center IP in a different country is treated as anomalous, triggering automatic session rotation/invalidation.
*   **Abuse Thresholds**: Initiating multiple large segment downloads on the same video within a few minutes (as we did during testing) triggers abuse protection, resulting in temporary session bans or immediate cookie invalidation.

---

## 🛠️ Step-by-Step Mitigation Strategies

To run the pipeline in production without constant manual cookie maintenance, implement the following steps:

### Strategy A: The Burner Account Workflow (Low Cost, High Success)
Do not use your main personal account. Using a burner account isolates your personal data and removes 2FA hurdles.

1.  **Create a Dedicated Google Account**: Set up a free Google account (e.g., `gta6.pipeline.bot@gmail.com`) with no 2FA.
2.  **Export from Private/Incognito Mode**:
    *   Open an **Incognito Window** in your browser.
    *   Log into YouTube using your burner account.
    *   Click on your cookie exporter extension (e.g., *Get cookies.txt LOCALLY*) and export in Netscape format.
    *   **Close the Incognito tab** (do NOT click "Sign Out" on YouTube, as signing out tells Google's servers to invalidate the session key immediately).
3.  **Overwrite the Cookies File**: Paste the raw contents into `www.youtube.com_cookies.txt` in the workspace.

Since the daily production pipeline only runs **once per day** for a single video, this low-frequency access is rarely flagged. A single burner cookie file can easily remain valid for **several weeks or months**.

---

### Strategy B: User-Agent Matching (Critical Fix)
To prevent YouTube from immediately revoking cookies due to a browser footprint mismatch, configure `yt-dlp` to use your exact browser User-Agent:

1.  Find your browser's User-Agent (go to [whatsmyuseragent.org](https://whatsmyuseragent.org/) and copy the string).
2.  Pass this User-Agent to `yt-dlp` in your downloader scripts (`editor.py`, `clip_analyzer.py`, `heatmap.py`):
    ```python
    # Example addition to cmd in editor.py
    cmd.extend(["--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36..."])
    ```

---

### Strategy C: Residential Proxies (The Ultimate Automation Bypass)
If you run the pipeline in GitHub Actions and want to completely eliminate data center IP blocks:

1.  Sign up for a cheap **Residential Proxy provider** (e.g., Webshare, Smartproxy, or Oxylabs).
2.  Configure `yt-dlp` to route all downloads through a residential IP proxy. This masks the cloud VM IP as a standard home internet connection.
3.  Pass the proxy option to your Python commands:
    ```python
    cmd.extend(["--proxy", "http://username:password@proxy_host:port"])
    ```
With a residential proxy, you will rarely need cookies at all, as YouTube treats the connection as a normal home user browsing the site.
