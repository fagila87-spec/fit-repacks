# FARHAN GAMEHUB

A polished starter for a game/project catalogue with searchable listings, game detail pages, a login-protected admin dashboard, upload support, download tracking, magnet/external links, and owner-managed admin accounts.

## Run on Windows

1. Install Python 3.11+ from python.org.
2. Extract this folder.
3. Double-click `run_windows.bat`.
4. Open `http://127.0.0.1:5000`.

First-run local demo login:
- Username: `farhan`
- Password: `farhan.811281`

**Before exposing this to the internet:** change the default password immediately, set a strong random `SECRET_KEY`, and set `INITIAL_ADMIN_USER` / `INITIAL_ADMIN_PASSWORD` before the first run. If the database has already been created, changing the environment variables will not change existing accounts; use the account management panel or reset the local demo database before deployment.

## Admin features

- `/login`: admin login
- `/admin`: dashboard and catalogue management
- Add/edit/delete catalogue entries
- Upload cover images and authorised distributable archives/ISO files
- Add magnet links and external HTTPS download URLs
- Track clicks on hosted direct downloads
- Owner can create/delete admin accounts and assign `admin` or `owner` roles

New admin passwords must be at least 12 characters. Passwords are stored as salted scrypt hashes, not plaintext.

## Important hosting notes

This is a local starter, not a production-hardened large-file distribution service. Do not run Flask's development server on the public internet. For deployment, use a production WSGI server, HTTPS, secure environment secrets, rate limiting, CSRF protection, backups, and object storage/CDN for large files. Set upload size limits based on your host. Magnet links only point to content; this site does not create or seed torrents.

Only upload or link to games/files you own or are authorised to distribute. Respect copyright and the terms of your hosting provider. Do not upload pirated repacks.
