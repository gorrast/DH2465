# Team portraits

The public team page uses transparent PNG cutouts so the colored CSS backgrounds show behind each person:

- hugo-wigh-removebg-preview.png
- nima-dentist-nobg.png
- knut-ovesjo-removebg-preview.png
- marcus-pramborg-removebg-preview.png
- gustaf-salenius-removebg-preview.png
- hugo-ankarcrona-removebg-preview.png

Keep the subject centered with the shoulders at the bottom. The existing JPG originals are retained.
Names, titles, filenames and backdrop colors are configured in app/project/team/page.tsx;
portrait sizing and framing are in styles/views/site.css. Missing photos display initials.
Rebuild/redeploy after replacing photos because this page is statically rendered.
