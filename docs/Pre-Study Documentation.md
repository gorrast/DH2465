# Conceptual Framing and Problem Solution Fit 
Pre-study document - Last updated: 27th September 2026
## Thesis
**Clearly isolate specific user friction point that our company is targeting**

Health-conscious wearable users who suspect a connection between their daily schedule and their sleep or stress have no easy way to check why their performance scores change. Doing so requires manually comparing two separate systems, for example a calendar and a health app, day by day, over enough time to see a pattern. This is tedious enough that almost no one does it consistently, so the suspicion is difficult to act on. Health watches can generate scores and summaries already, but only using the wearables own sensor data, which means there is nothing that connects the health indicators and the user's schedule.

What would falsify this thesis:

Target users report they've never actually wondered about this connection.
Target users report they've tried manual comparison and found it easy or unnecessary.
Target users say they'd rather ask a doctor/coach than see a pattern themselves (friction is real, but the demanded solution is different from ours).

****
## Solution Hypothesis
**Document how the proposed product would solve this friction point in a way that competitors cannot**

We connect a user's calendar and their existing wearable(s) automatically, and run statistical analysis across both to surface specific, dated patterns ("meetings after 7pm correlate with 20% lower sleep efficiency") in a weekly report, removing the manual cross-referencing that makes this friction unsolved today. Because the analysis works across any wearable brand and treats the calendar as an equal data source, it produces insights that single-brand wearable apps or manual methods have difficulty replicating.

Why incumbents are structurally unlikely to close this gap themselves: the two data sources that matter (health, schedule) are owned by different companies with no shared incentive to combine them. Apple, Google, and the wearable brands each have a business reason to keep users inside their own ecosystem, not to make a competitor's calendar or a competitor's sensor data equally as important.

Core assumptions to test:

Users trust a third party with both calendar and health data enough to connect both.
The patterns found feel specific and interesting.
Users change behavior after seeing a pattern.
A meaningful share of the target market is not already fully satisfied by their device's built-in AI insights.



****
## Target Audience/Customer Analysis
**Outline the profile of early adopters who experience this friction point most intensely**

- Segment the market
	- Performance athletes, might already track e.g. HRV, recovery and training load. In need of more precision and information.
	- Workers managing stress or burnout, wearable owners who feel that e.g. work is affecting them physically. Need validation and data to change schedule and habits.
	- People with sleep issues, might already use a sleep-tracker. Need reassurance and ways of finding better sleep. 
	- Casual quantified-self users who want fun applications, enjoy data for their own sake, low commitment and risk.
- Interviews
	- Current behaviour
	- Current workarounds/solutions
- Willingness to pay
	- What do they currently pay for related products/services?
	- Oura/Whoop memberships?
	- Therapy? Other apps?
- Market Sizing, prove the economic scale justifies development
	- TAM (Total Addressable Market), all wearable owners globally (smartwatch + smart ring + fitness band), on the order of several hundred million active devices.
	- SAM (Servicable Addressable Market), wearable owners who also use a digital calendar consistently and are in geographies where you can legally operate.
	- SOM (Servicable Obtainable Market), Realistic capture in year 1–2, based on comparable app category conversion rates (health/fitness apps typically see low-single-digit-percent conversion from install to paid subscription)
 
****
## Competitive and landscape analysis
**Map competitors and other alternatives to figure out how our product can differentiate itself**

**Market sizing**
The global wearable technology market was valued at roughly $92.9 billion in 2025 and is projected to reach approximately $103.1 billion in 2026, growing at a compound annual rate of about 12%. Smartwatches alone were valued around $38.5 billion in 2025.

Unit-shipment trends matter more than revenue for our addressable user base. Overall smartwatch shipments are forecast to decline roughly 4% in 2026 as replacement demand slows, while smart ring shipments (Oura's category) are forecast to grow about 53% to 6 million units in 2026, continuing at a projected 32% CAGR through 2030. This suggests the highest-intent, most health-data-literate segment of your addressable market (ring wearers) is currently the fastest-growing one, even though smartwatches remain the larger installed base by volume.

- Competitor Mapping
	- Identify primary (e.g. Oura's own AI Advisor, WHOOP Coach, Fitbod-style tools, Gyroscope, Bearable), secondary, and indirect (e.g. a good therapist, a habit-tracking spreadsheet, the native Apple/Garmin apps' own insights) competitors to evaluate what they fail to deliver to customers
	- What data do they use, what don't they do well, pricing, retention signals (e.g. App Store reviews as a proxy)
	- Identify actual differentiation, most apps will or already have implemented 'AI insights', put emphasis on the calendar integration and other functionality
	- If Garmin/Oura/Whoop launch their own calendar integration, what do we have left?
- Legal and regulatory compliance checks
	- Review whether data privacy laws (like GDPR), medical clearances, or business licensures act as bottlenecks

****
## Business/Financial Model Design
- Business model canvas/Lean canvas
	- Value proposition
	- Channels
	- Customer relations
	- Revenue streams
	- Cost structure
	- Key partners
	- Key resources
-  Revenue model options
	-  Subsription
	-  Freemium
	-  B2B2C
	-  Data/research angle
-  Unit economic estimate
	-  Cost per customer (LLM inference, hosting, push notifications etc)
	-  Expected ARPU (Average revenue per user)
	-  Customer acquisition cost (CAC)
-  Cash requirements to reach MVP
	-  How much is needed before reaching self-sustaining revenue?
-  Human Capital

****
## System Design
- Data collection
	- Scrape Garmin Connect to extract information and connect to our app/site
	- Extract data directly from devices and import
- Database design
	- Structured data, SQL
	- Postgres?
 
****
## Risk Assessment
**Risk categories**
- Platform/partner risks
	- Garmin's paused developer program
	- AI-restrictions
	- WHOOP 10 user approval bottleneck
	- Apple policy changes to Healthkit
- Legal/regulatory
	- GDPR special-category health data, is a DPIA needed?
	- EU AI Act
	- Medical-device classification
- Market/adoption risks
	- Insights might feel old/gimmicky after a couple of weeks
	- Users don't trust AI-generated helath claims
	- Low willingness to pay
- Technical/data quality
	- Sparse or inconsistent data from devices
	- Statistical false positives
	- Bad AI analysis
- Financial
	- Runway vs time-to-first-revenue
	- LLM inference costs scaling faster than revenue
- Team/execution
	- No healthcare professional
- Reputation and ethics
	- Incorrect health insights, who is liable?