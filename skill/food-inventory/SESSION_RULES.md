# Food Inventory Session Rules

When a user is clearly listing food inventory to be logged, do not stay in conversational collection mode unless key details are still missing.

## Hard rules

1. If the user gives explicit inventory items with enough detail to store them, you must write them to the database in the same turn using:
   - `python3 {baseDir}/scripts/fooddb_sqlite.py add ...`
   - or `update`/`delete` when appropriate.
2. Do not say **Added**, **Logged**, **Got it**, or any equivalent confirmation unless the DB write already happened in that same turn.
3. Do not ask “want me to log what you’ve given me so far?” after the user has already asked to log inventory. Log it.
4. If a user is sending a multi-message batch, keep a concise running summary if needed, but persist each complete item as soon as it is clear enough.
5. If an earlier transcript item is explicitly revoked (example: “ignore that radishes message”), do not store it.
6. If expiration is unknown, omit `expirationDate`; GrubTrack may add a visibly labeled estimate.
   If `LOCAL.md` says `expiration_prompt: always`, ask for the printed date instead.
7. Default assumption is utilitarian: inventory statements are instructions, not brainstorming.

## Preferred behavior for voice transcripts

- Correct obvious speech-to-text mistakes when confidence is high.
- After a transcript with several complete items, write them immediately.
- Reply briefly with what was logged, not with a question that delays persistence.

## Failure to avoid

Bad:
- Summarizing items from chat
- Saying they were added/logged
- Not calling the DB script

Good:
- Parse items
- Persist to DB immediately
- Then confirm briefly
