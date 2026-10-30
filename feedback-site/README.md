# The guest feedback form

The form guests open by scanning the QR code at the stall. It is a static page
hosted on Netlify; THE HOST reads the submissions back through the Netlify API
and shows them on the dashboard's **Feedback** page.

Live at: <https://biteandpour.netlify.app/>

## What is in here

| Path | What it is |
|---|---|
| `netlify-deploy/` | The site that gets deployed: `index.html`, `style.css`, `script.js`. Nothing else. |
| `bite-and-pour-feedback-qr.png` | The printable QR card, branded, for the table at the stall. |
| `bite-and-pour-feedback-qr-plain.png` | The bare QR code, for putting on a poster or a menu. |

Both QR images point at the address above.

## Deploying it

1. Open <https://app.netlify.com/drop> and drag the **`netlify-deploy`** folder
   onto it (or, for an existing site, Deploys → drag the folder).
2. In the site's settings, go to **Forms → Enable form detection**.
3. **Redeploy** the site. Form detection only scans a deploy made *after* it was
   switched on, so a site deployed first and enabled second collects nothing.
4. Send a test submission from a phone, then check Netlify's **Forms** tab: a
   form named `feedback` should be listed with one submission.

Step 3 is the one that is easy to miss. If the Forms tab shows no form at all,
the deploy happened before detection was enabled — redeploy and try again.

**Never deploy the `BITE&POUR/` folder.** It is Rehman's original PHP version,
kept locally for reference and deliberately not committed. Netlify does not run
PHP, so it would serve those files as plain downloads — including `auth.php`,
which contains a hard-coded fallback login.

## How THE HOST reads it

The backend asks Netlify once a minute, using two settings in `backend/.env`:

- `NETLIFY_TOKEN` — a personal access token (Netlify → User settings →
  Applications → Personal access tokens)
- `NETLIFY_SITE_ID` — the site's API ID (Site configuration → General → Site
  information)

Leave them blank and the import is simply off; the Feedback page says so. The
token is never logged, never printed and never written to any file.

Each submission is stored once, keyed on its Netlify submission id, in the
`form_feedback` table — separate from the `feedback` table, which is what
guests ask THE HOST to pass on by voice. The dashboard shows the two on
separate tabs and never mixes them.

## Changing the form

The fields THE HOST stores are `item`, `overall_rating`, `taste_rating`,
`presentation_rating`, `value_rating`, `liked_most`, `improvement`,
`buy_again` and `one_word`. Renaming one of those `name=` attributes in
`index.html` means that answer stops being stored; adding a new field needs a
column in `form_feedback` as well.

The form's own name must stay `feedback` (the `form-name` hidden input and the
`name` on the `<form>`), or set `NETLIFY_FORM_NAME` in `.env` to match.
