# Clone: separate monthly artworks per book

New link submissions use `source_variants`. Existing `source_expand` items retain their former shared-original behavior to avoid mixing already-generated grid pages with replacement artworks during resume.

For K valid source artworks and N books (K=1..12, N=1..5), fetch once and plan 12×N new artworks. Month m uses source m when m≤K; otherwise source 1 guides a new concept. Each source produces N distinct variants. Source files are references only; they are never copied into new books as final monthly artwork.

New submissions use `planning_mode=single_session`: one pinned account fetches sources and one idea chat writes all N variants for each month, then commits the complete 12×N plan before any image generation. Replies can span multiple turns in that same chat. There is no separate idea-review stage. Completed assignments, the account and the full chat URL are saved after each turn. Resume uses the same account/chat; missing or inaccessible chat state stops planning instead of silently creating a new idea session. Existing groups without this mode keep their earlier planner during resume.

Code still validates JSON, assignment IDs, counts and exact duplicate prompts before saving. Long-chat responses are detected by message identity as well as visible turn counts, since ChatGPT can virtualize old turns and shrink the DOM while a new response is complete.

The shared group persists reference files, prompt assignments and generated images. Each image has an assignment ID such as b02m07. Prompts are concise because common style/orientation rules are appended by the renderer. Save the image in the shared group before copying it into the book, so an interrupted copy can resume without another generation. Grid generation is unchanged.

Generation is distributed across the common paid-account pool. Each book shares the current Chrome/RAM image capacity with books that still need artwork, rather than allocating by the raw account count. A finished book stops consuming an artwork share. Active-book scans are briefly cached to avoid repeated full queue scans. A worker reuses its chat for its assigned images, attaches the correct reference for each request and yields after saving an image when another pool request is waiting. Stable waiter IDs survive scheduler retries so those waiting requests remain visible to current owners; unused IDs are removed when the worker count shrinks, and all IDs are cleaned up on finish/cancellation. No parent account is held while these workers borrow accounts. Global Chrome/RAM limits remain authoritative.

Every new artwork must pass image decoding, landscape/size validation, duplicate-byte rejection and a visual check for natural upright orientation, artwork-only framing and meaningful variation from its source. A failed visual check triggers a corrective image request in the same chat; no failed image is accepted into the book. These checks reduce failures but model judgments are not a guarantee of visual quality.

Downloaded candidate images are persisted before visual verification. If that text check fails due to network/DOM errors, resume reattaches the candidate and source for verification instead of generating another image. Rejected candidates are preserved separately; only approved images enter a book's artwork directory.

The two earlier Book Boyfriend books shared all 12 original files byte-for-byte. Source 1 was a 717×647 tilted calendar mockup including paper, binding and the date grid. New extraction instructions require perspective correction and clean artwork crops; generation explicitly reconstructs an upright flat artwork even when its source is a tilted product photograph.

Existing completed books are preserved. They require a new submission to receive the new artwork flow; changing prompts does not retroactively replace their files.
