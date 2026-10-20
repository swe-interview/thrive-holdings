Back office task of filing a tax return
Historically you as an accountant
Client - get a bunch of their form s
Thinking about - what context needs to go to into their tax return
Extracting their data - manually putting it into a tax return

Know when to extract
Workpaper curation

Documents clients -> organizing -> workpaper + bookmarks

bookmarks
- wages
    - anything W2 -> wages
        - OCR, W2 forms follow structured format
        - deterministic (is_w2)
- interest
- dividend

classify_doc (deterministic)
    - W2 -> wages
    - 1090 -> schech b interest

LLM based
- preparse docs - titles, headings, form number, company/entity charles shwab, account #
    - to an LLM - can you classify

maps -> submit to tax return

1. define workpaper schema
2. preprocess docs (OCR, parsing)
    page_n -> page_n+1 OCR parsed - ask if it's a new page

3. classify segments (LLM or determinstic)






