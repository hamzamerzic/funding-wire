# Funding Wire design

Inherits Möbius's theme; do not change the owner's shell to style this app.

- Operate/read surface: an ordered funding ledger, not a financial-performance dashboard.
- One column, maximum 1000px; 22px phone padding, 40px wide-screen padding; compact vertical rhythm.
- Typography uses --font. Company and amount share a 23px baseline on phones and 26px on wide screens. Amount numerals are tabular.
- Use --bg, --surface, --surface-2, --text, --muted, --border, --accent. The accent identifies sectors, focus and saved state, not deal quality.
- Border-separated reports. No cards inside cards, charts without evidence, valuations mixed with raise totals, or implied completeness.
- Search, icon-based native sorting and Saved share one row. Region, stage and sector remain visible beneath it with native selects. Accented, underlined publisher links and Save are at each report's foot, with 44px touch targets. Backer labels sit inline; valuations remain distinct from round totals. Refresh completion belongs in the top status, not a redundant toast.
- Loading, unavailable sources, unknown details, no matches and no saved companies have explicit copy. Existing reports remain visible during refresh failure.
- Reduced-motion users see no spinner animation. The only other motion is the Save state transition.
