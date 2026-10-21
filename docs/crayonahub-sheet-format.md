# Crayonahub Google Sheets format

User-approved format, updated 2026-10-17.

Target spreadsheet: `1qD3M9OQ57JPdW0rV_X3_-ik4pSvywMuPCPNyPLs_CGg`, tab `Trang tính1` (gid 0).

## Columns

`SKU | Description | Tags | Title | Sizes | Paper | Design`

Paper is a separate variant column added by the user on 2026-10-17: Matte for SM, Glossy for SG, taken from the actual CSV variant's Option3 Value. Parent Paper is blank. Description still includes the general Paper detail. Design is now column G.

Seven-column receiver deployed as version 6 at 20:17 Bangkok time on 2026-10-17. A real sync of WCB-TCH-TAYYB was acknowledged; browser readback exactly matched all five expected rows, Paper values were Matte/Glossy/Matte/Glossy, and each Design retained 26 URLs. Related verification: 26 Python tests plus 10 receiver tests passed. Same endpoint/secret; no installer rebuilt.

Description is plain text, like listing.txt, never HTML. Preserve paragraphs and bullet lines. In Details, after Sizes and before Binding, include exactly:

```text
- Paper: Matte or Glossy
```

## Product rows

Use five rows per book: parent SKU, then `-11SM`, `-11SG`, `-14SM`, `-14SG`. Description, Tags and Title belong on the parent row. Parent Sizes, Paper and Design are blank. Variant rows contain SKU, Sizes, Paper and Design; other fields are blank. No Printable variants in this sheet.

Design contains 26 URLs in one cell, one URL per line, without numbering, labels or pipe separators:

1. front_cover.png
2. m01_month.png, then m01_grid.png
3. Repeat month artwork then grid through m12_month.png and m12_grid.png
4. back_cover.png

11SM and 11SG share the 11x8.5 URLs. 14SM and 14SG share the 14x11.5 URLs. Future sync must upsert by SKU to avoid duplicates.

## Display

Column widths A–G: 180, 220, 160, 220, 90, 90, 260 px. Data row height: 64 px. Left/top alignment, clipped overflow, 100% zoom. Keep full cell content despite the compact display. Column order rechecked against the live sheet on 2026-10-17.

## Implementation status

Both CSV publish commands call `publish.sheets.sync_books` after successful R2 upload and CSV export. Sync upserts the canonical printed variants by SKU, with Paper in the plain-text Description. Failures remain pending and retry on the next publish; successfully synced unchanged data is skipped.

Printify exports (`exported_at` or `exported_csv`) are excluded from Crayonahub publishing before any R2 call, including explicit selections and CLI runs. This restriction is intentionally one-way, matching the user's request.

The Google-side receiver is `tools/crayonahub_sheet.gs`. Live synchronization requires a one-time Web app deployment and local `sheets.endpoint` / `sheets.secret` configuration. Source changes are not packaged into an installer yet.

Deployed Apps Script project: https://script.google.com/u/0/home/projects/1t3Ufx54SfQGZvLK5pi7w-61mcHTzfLq4R2QjwD7Odp7J1DrnceLXL97o/edit . The owner explicitly approved deployment and secret creation, then completed Google authorization. Active version 4 was deployed on 2026-10-17 at 19:28 Bangkok time, keeping the same endpoint. The /exec endpoint and shared secret are saved in the local ignored calforge.json; no secrets are stored here.

Live verification passed on 2026-10-17: canonical WCB-GD-UW4UN data already present in the sheet was fed through CSV publish with an upload-prohibiting S3 adapter. It updated the five existing rows. A repeated publish skipped both upload and sync; a direct signed replay was also acknowledged by Google. Sizes remain plain `11 x 8.5` / `14 x 11.5`, matching the sheet. This validates the real Google receiver and publish orchestration without uploading any test images to R2. No installer has been rebuilt for these changes.

Final browser verification confirmed exactly five data rows, all cell values matching the original fixture, Paper present, and 26 Design URLs per printed variant. Version 4 uses `setRowHeightsForced` so multiline Description and Design cannot expand the compact row heights. Related verification: 56 Python tests and 10 JavaScript checks passed.

## One-time connection

1. Create an Apps Script project. Put `tools/crayonahub_sheet.gs` in Code.gs and use `tools/crayonahub_sheet_appsscript.json` as appsscript.json.
2. In Script Properties, set `SHEET_SYNC_SECRET` to a randomly generated secret of at least 32 characters. The same secret is entered in the tool's R2 / Sheet settings; never put it in a sheet cell or URL.
3. Deploy a Web app executing as the owner, accessible to Anyone. Google requires owner authorization for the spreadsheet scope. The receiver itself accepts only signed requests and targets only the fixed spreadsheet above. A person holding the secret can update this target through the receiver; send it only to trusted tool users.
4. Paste the /exec URL and secret into Khoá R2 → Google Sheet on each machine. Leave the secret input blank when editing other settings to preserve it. Existing Google browser logins are not used by the tool's sync.
5. Test an existing product and repeat the same publish: it should update the same SKUs, with no duplicate rows and no unchanged R2 files uploaded.

The receiver serializes writes with Apps Script LockService, validates all headers before writing and refuses duplicate target SKUs already in the sheet. A failed/partial request can be repeated safely. It does not clear unrelated rows or columns. Rows are compact (64 px), Design is newline-separated, and plain-text cell content is preserved.

## Description and viewer SKU filtering

On 2026-10-17, A2:B2 was found merged: selecting B2 resolved to A2:B2 and showed the SKU instead of Description. The cells were separated and WCB-TCH-TAYYB's full Description restored from its local listing, including Paper. The receiver now calls `breakApart()` on each six-cell output row before writing, preventing merged cells from silently losing Description again.

This fix was deployed as version 5 at 19:39 Bangkok time, using the existing endpoint. A real sync of WCB-TCH-TAYYB was acknowledged. Browser readback confirmed all five rows match the expected listing/Design payload, B2 resolves separately, and the 1,611-character Description includes Paper. Ten receiver tests pass, including the merged-cell regression.

Saved filter view: **Tìm SKU — lọc riêng**, view ID `747434666`:
https://docs.google.com/spreadsheets/d/1qD3M9OQ57JPdW0rV_X3_-ik4pSvywMuPCPNyPLs_CGg/edit#gid=0&fvid=747434666

View-only users can create their own temporary filter view (Data → Create filter view), then open the SKU column filter and enter a base SKU to find the parent plus its variants. This does not require edit rights and does not change another person's view. Do not add a shared editable search cell or broaden sharing permissions to implement search. Google's viewer behavior is documented at https://support.google.com/docs/answer/3540681 .

Google references: https://developers.google.com/apps-script/guides/web and https://developers.google.com/apps-script/reference/lock/lock-service .
