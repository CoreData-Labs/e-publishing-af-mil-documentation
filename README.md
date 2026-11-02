# 📚 E-Publishing AF.MIL Documentation Library

> A public, organized mirror of official U.S. Air Force and Department of the Air Force publications, instructions, manuals, handbooks and forms from the **Air Force e-Publishing** website, collected for **education, research, AI/ML study, professional development and community learning**.

**Source website:** <https://www.e-publishing.af.mil/>
**Repository:** <https://github.com/PrajwalKoirala638/e-publishing-af-mil-documentation>
**License:** MIT (for the repository's own scripts, structure and original text; see [Licensing and Legal Notes](#-licensing-and-legal-notes))

---

## 📑 Table of Contents

1. [What Is This Repository?](#-what-is-this-repository)
2. [What Is Air Force e-Publishing?](#-what-is-air-force-e-publishing)
3. [Repository Structure](#-repository-structure)
4. [Types of Documents You Will Find](#-types-of-documents-you-will-find)
5. [Understanding Publication Numbers](#-understanding-publication-numbers)
6. [Benefits of These Documents](#-benefits-of-these-documents)
7. [Benefits for Education](#-benefits-for-education)
8. [Benefits for AI and Data Science](#-benefits-for-ai-and-data-science)
9. [Benefits for Careers and Professional Growth](#-benefits-for-careers-and-professional-growth)
10. [Benefits for Communities and Organizations](#-benefits-for-communities-and-organizations)
11. [How to Use These Documents (Step by Step)](#-how-to-use-these-documents-step-by-step)
12. [How to Improve Yourself with These Docs](#-how-to-improve-yourself-with-these-docs)
13. [How to Improve Your Community with These Docs](#-how-to-improve-your-community-with-these-docs)
14. [How Anyone Can Use This Library](#-how-anyone-can-use-this-library)
15. [Using the PDFs with AI Tools](#-using-the-pdfs-with-ai-tools)
16. [Sample 12-Week Study Plans](#-sample-12-week-study-plans)
17. [Quick Start for Developers](#-quick-start-for-developers)
18. [Keeping the Library Up to Date](#-keeping-the-library-up-to-date)
19. [Contributing](#-contributing)
20. [Responsible Use and Safety](#-responsible-use-and-safety)
21. [Licensing and Legal Notes](#-licensing-and-legal-notes)
22. [Frequently Asked Questions](#-frequently-asked-questions)
23. [Glossary](#-glossary)
24. [Disclaimer](#-disclaimer)

---

## 🎯 What Is This Repository?

This repository is a **documentation library**. It gathers publicly releasable PDF documents from the Air Force e-Publishing website and stores them in one place so that students, teachers, researchers, developers, veterans, volunteers, writers and curious people can **read, search, study, cite and learn from them**.

The goal is simple:

- 🔎 **Make it easy to find** official guidance without navigating many menus.
- 📖 **Make it easy to learn** from real-world, professionally written procedures.
- 🧠 **Make it easy to analyze**, including text mining, search and AI-assisted study.
- 🤝 **Make it easy to share** knowledge with anyone, anywhere.

All PDFs are stored in the **`PDFs/`** folder. If you are new, start with the [How to Use These Documents](#-how-to-use-these-documents-step-by-step) section.

> **Note:** This is an independent, community-maintained collection. It is **not** an official U.S. Air Force or Department of Defense website, and it is not endorsed by them. Always confirm current, authoritative versions at the official source.

---

## 🛰️ What Is Air Force e-Publishing?

The **Air Force e-Publishing** website (`e-publishing.af.mil`) is the official U.S. government site where the Department of the Air Force posts its **departmental publications and forms**. Publications on the site are the written rules, procedures and guidance that organize how a very large organization operates.

In general, the site offers:

| Capability          | What it gives you                                                                                        |
| ------------------- | -------------------------------------------------------------------------------------------------------- |
| **Publications**    | Instructions, manuals, policy directives, pamphlets, handbooks and guidance memorandums                  |
| **Forms**           | Official forms used across the Department (for example, AF Forms and other standard forms)               |
| **Search**          | Look up a publication by number, title, keyword or organization                                          |
| **Product index**   | Browse by category, publishing organization or product type                                              |
| **Version control** | Each publication shows its release date, certification date and whether it supersedes an earlier version |
| **Free access**     | Most publications are cleared for public release and require no login to download                        |

Why does this matter? Because these documents are some of the **largest, best-organized collections of operational, administrative, safety, training, legal-process, medical-support, logistics and leadership guidance** that any person can read for free.

---

## 🗂️ Repository Structure

```text
e-publishing-af-mil-documentation/
├── PDFs/                  # All downloaded publications and forms (PDF format)
├── README.md              # This file
├── LICENSE                # MIT license for the repository's original content
└── .gitignore             # Files Git should ignore
```

**Tip:** If the `PDFs/` folder grows large, consider organizing it into subfolders, for example:

```text
PDFs/
├── instructions/          # AFI / DAFI files
├── manuals/               # AFMAN / DAFMAN files
├── policy-directives/     # AFPD / DAFPD files
├── pamphlets/             # AFPAM / DAFPAM files
├── handbooks/             # AFH / DAFH files
├── forms/                 # AF Forms and other forms
└── guidance-memos/        # Memorandums and interim guidance
```

> If you add folders, update this section so newcomers always have an accurate map.

---

## 🧾 Types of Documents You Will Find

Air Force publications follow a consistent hierarchy. Understanding that hierarchy helps you pick the right document for the right purpose.

| Type                             | Abbreviation           | Purpose                                                                 | Typical Reader                |
| -------------------------------- | ---------------------- | ----------------------------------------------------------------------- | ----------------------------- |
| **Policy Directive**             | AFPD / DAFPD           | States _what_ policy is and _who_ is responsible. Short and high level. | Leaders, planners             |
| **Instruction**                  | AFI / DAFI             | States _how_ to carry out policy. Mandatory steps and responsibilities. | Supervisors, program managers |
| **Manual**                       | AFMAN / DAFMAN         | Detailed, technical _procedures_.                                       | Specialists, technicians      |
| **Pamphlet**                     | AFPAM / DAFPAM         | _Guidance_ and _information_, usually non-directive.                    | Anyone seeking explanation    |
| **Handbook**                     | AFH / DAFH             | Practical _how-to_ reference material.                                  | Learners, new staff           |
| **Guidance Memorandum**          | AFGM / DAFGM           | _Immediate_ changes to guidance before a full revision.                 | Everyone affected             |
| **Forms**                        | AF Form, DD Form, etc. | Standard documents for requests, records and reports.                   | Anyone completing a process   |
| **Joint and other publications** | Varies                 | Guidance shared across services or agencies.                            | Cross-service teams           |

**Mandatory vs. informational:** Directive publications (policy directives, instructions, many manuals) use words like _shall_ and _must_. Pamphlets and handbooks generally _explain_ and _recommend_. When reading, always notice which kind of document you have.

---

## 🔢 Understanding Publication Numbers

Publication numbers carry meaning. A common pattern looks like this:

```text
DAFI 36-2670
│    │  │
│    │  └── Unique number within the series
│    └───── Functional series (36 = Personnel, for example)
└────────── Publication type prefix (Department of the Air Force Instruction)
```

Common functional series you may encounter (the series numbering is a long-standing convention; confirm exact titles on the official site):

| Series        | General Subject Area                          |
| ------------- | --------------------------------------------- |
| **10-series** | Operations                                    |
| **11-series** | Flying operations                             |
| **13-series** | Space, command and control                    |
| **16-series** | Operations support                            |
| **17-series** | Cyberspace and information                    |
| **21-series** | Maintenance                                   |
| **23-series** | Supply and logistics                          |
| **24-series** | Transportation                                |
| **31-series** | Security                                      |
| **32-series** | Civil engineering                             |
| **33-series** | Communications and information management     |
| **34-series** | Services and morale                           |
| **35-series** | Public affairs                                |
| **36-series** | Personnel, education and training             |
| **38-series** | Manpower and organization                     |
| **40-series** | Medical                                       |
| **41-series** | Health services                               |
| **44-series** | Medical (clinical and public health programs) |
| **51-series** | Law                                           |
| **52-series** | Chaplain services                             |
| **61-series** | Scientific and technical information          |
| **63-series** | Acquisition                                   |
| **64-series** | Contracting                                   |
| **65-series** | Financial management                          |
| **90-series** | Command policy                                |
| **91-series** | Safety                                        |
| **99-series** | Test and evaluation                           |

**Reading tip:** If you know the _subject_ you care about (for example, safety, education, cyber), you can jump straight to its series.

---

## 🌟 Benefits of These Documents

### 1. Free, authoritative information

Publications come from the organization that wrote the rules. That means **primary-source accuracy** rather than third-hand summaries.

### 2. Real-world process design

Few places show how to build **repeatable, auditable, safe processes** at scale. These documents are examples of:

- Clear **roles and responsibilities** (who does what)
- **Step-by-step procedures** (how it is done)
- **Checklists and attachments** (how to verify)
- **Reference lists** (where to learn more)
- **Terms and definitions** (so everyone means the same thing)

### 3. A model for professional writing

Government publications are written to be unambiguous. Studying them improves:

- Technical writing
- Policy writing
- Standard operating procedure (SOP) writing
- Documentation habits for software and engineering teams

### 4. Broad subject coverage

In one library you can touch topics such as leadership, education and training, safety, health and wellness, logistics, cybersecurity practices, information management, legal processes, public affairs, finance, acquisition and more.

### 5. Searchable, copyable-text PDFs

Most modern publications are text-based PDFs, which means you can **search, highlight, annotate and extract text** for study and analysis.

### 6. A stable reference for citation

Each document has a number, title and date, so you can cite it precisely in essays, theses, reports and presentations.

### 7. Accessible to everyone

Anyone with a phone, tablet or computer and a PDF reader can open these files. No special software or subscription is required.

---

## 🎓 Benefits for Education

| Audience                           | How the documents help                                                                                                                                                   |
| ---------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **High school students**           | Learn about careers, leadership, teamwork, discipline, safety and how large organizations function. Great for civics, JROTC-style study, essays and debate prep.         |
| **College students**               | Primary sources for public administration, management, political science, human resources, logistics, aviation, aerospace, cybersecurity, public health and law classes. |
| **Graduate researchers**           | Citable material for policy analysis, organizational studies, process improvement research and case studies.                                                             |
| **Teachers and trainers**          | Ready-made examples of _rubrics_, _checklists_, _lesson-planning structures_ and _performance standards_.                                                                |
| **Self-learners**                  | A free curriculum for leadership, communication, project management and process discipline.                                                                              |
| **Technical writers**              | Real examples of consistent structure, numbering, definitions and attachments.                                                                                           |
| **Military families and veterans** | Understand programs, entitlements, processes and terminology in plain, official language.                                                                                |

### Education-focused topics worth exploring

- **Training and education programs:** how learning is organized, evaluated and recorded.
- **Professional military education concepts:** leadership development frameworks and progression.
- **Instructional systems and assessment:** how objectives, standards and evaluations are structured.
- **Academic and career pathways:** how certifications, credentialing and continuing education are described.
- **Language, culture and communication guidance:** how organizations train for clear communication.

---

## 🤖 Benefits for AI and Data Science

These documents are valuable not because they "teach AI to be military," but because they are **large, consistent, high-quality text** and **excellent practice material** for modern data and language workflows.

### What you can build or learn

| Project idea                                                           | Skills practiced                                                                           |
| ---------------------------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| **Semantic search engine** over the PDFs                               | Text extraction, embeddings, vector databases                                              |
| **Question-answering assistant** (RAG: retrieval-augmented generation) | Chunking, retrieval, prompt design, citation of sources                                    |
| **Document summarizer**                                                | Summarization, evaluation, long-document handling                                          |
| **Publication relationship graph**                                     | Named-entity extraction, reference parsing, graph analysis (which publication cites which) |
| **Glossary and acronym extractor**                                     | Pattern matching, regular expressions, text cleaning                                       |
| **Topic modeling and clustering**                                      | NLP, unsupervised learning, visualization                                                  |
| **Change tracker**                                                     | Diffing versions, detecting supersession and updates                                       |
| **Accessibility checker**                                              | Reading order, alt text, tagged-PDF auditing                                               |
| **Table and form extraction**                                          | OCR, table detection, structured data output                                               |
| **Compliance checklist generator**                                     | Instruction following, structured output, verification                                     |

### Why this text is good for AI study

- **Consistent structure:** chapters, paragraphs, numbered requirements, attachments.
- **Defined vocabulary:** glossary sections make entity and acronym extraction easier.
- **Cross-references:** each document points to others, enabling graph and citation work.
- **Version metadata:** release dates and supersession info are useful for temporal reasoning.
- **Public availability:** easier to share for teaching, benchmarks and tutorials.

> ⚠️ **Always verify.** Any AI-generated answer based on these documents can be wrong or out of date. Treat AI output as a _starting point_ and check the original PDF and the official website before acting on anything important.

---

## 💼 Benefits for Careers and Professional Growth

- **Leadership and management:** learn how responsibilities, authorities and accountability are written down.
- **Project and program management:** study planning, risk, approval and review processes.
- **Safety culture:** see how risk assessments, inspections and reporting are structured.
- **Cybersecurity and IT governance:** understand policy layers, roles and documentation expectations.
- **Human resources and training:** examine how performance, development and records are handled.
- **Logistics and supply chain:** read about accountability, inventory and sustainment concepts.
- **Healthcare administration:** explore how health programs and support processes are described.
- **Legal and compliance:** see how rules, exceptions and approvals are written clearly.
- **Communication skills:** practice reading dense, formal documents quickly and accurately.
- **Interview and application prep:** become familiar with official terminology and organization structure if you are considering military or government service.

---

## 🏘️ Benefits for Communities and Organizations

Not only individuals benefit. **Groups** can use these documents as templates and inspiration:

| Community type                                    | Practical uses                                                                 |
| ------------------------------------------------- | ------------------------------------------------------------------------------ |
| **Schools and clubs**                             | Build club bylaws, safety plans, event checklists and leadership programs.     |
| **Nonprofits and volunteer groups**               | Borrow the _structure_ of policies, roles and review cycles to write your own. |
| **Local emergency teams and neighborhood groups** | Model preparedness checklists and clear chains of responsibility.              |
| **Small businesses**                              | Adapt the style of SOPs, safety rules and training records.                    |
| **Libraries and learning centers**                | Offer a free reference collection and host study circles.                      |
| **Online communities and study groups**           | Run reading challenges, discussion threads and Q&A sessions.                   |
| **Veteran and family support groups**             | Share plain-language explanations of programs and processes.                   |

> You are not copying military authority. You are **learning from well-documented process design** and adapting it to your own context.

---

## 🧭 How to Use These Documents (Step by Step)

### Step 1: Get the files

**Option A: Download a single file**

1. Open the `PDFs/` folder on GitHub.
2. Click a file name.
3. Click the **Download raw file** button (or use "View raw").

**Option B: Download everything**

1. Click the green **Code** button on the repository page.
2. Choose **Download ZIP**.
3. Unzip the file on your computer.

**Option C: Clone with Git**

```bash
git clone https://github.com/PrajwalKoirala638/e-publishing-af-mil-documentation.git
cd e-publishing-af-mil-documentation
```

### Step 2: Open and read

Use any PDF reader: your browser, Adobe Acrobat Reader, Preview (macOS), Okular, Evince, Foxit, or a mobile app.

### Step 3: Find what you need

- Use **Ctrl+F** (or **Cmd+F**) to search inside a PDF.
- Use your computer's file search to find a number or keyword in file names.
- Use the command line to search many PDFs at once (see below).

**Search all PDFs by keyword (Linux/macOS, using `pdfgrep`):**

```bash
pdfgrep -rin "training" PDFs/
```

**Search file names:**

```bash
find PDFs/ -iname "*36-2*"
```

### Step 4: Read in a smart order

For any publication, follow this reading pattern:

1. **Title page / summary of changes:** what is this and what is new?
2. **Table of contents:** map the document.
3. **Chapter 1 (Overview / Purpose / Applicability):** who and what this covers.
4. **Roles and responsibilities:** who does what.
5. **The chapter relevant to your question.**
6. **Attachments / glossary / references:** definitions and linked documents.
7. **Cited publications:** follow the references to go deeper.

### Step 5: Take notes

Use a simple template:

```markdown
## Notes: [Publication Number & Title]

- **Date / version:**
- **Purpose in one sentence:**
- **Key requirements (3–7 bullets):**
- **Roles involved:**
- **Terms I had to look up:**
- **Related publications:**
- **How I could apply this idea:**
```

### Step 6: Verify against the official source

Before relying on any document for a real decision, **check that you have the current version** at <https://www.e-publishing.af.mil/>.

### Step 7: Cite correctly

Example citation format:

```text
Department of the Air Force. (Year). Publication Title (Publication Number).
Retrieved from https://www.e-publishing.af.mil/
```

---

## 🌱 How to Improve Yourself with These Docs

### Build a daily reading habit

- **15 minutes a day:** read one section, write a 3-sentence summary.
- **Weekly goal:** finish one short publication or one chapter of a longer one.
- **Monthly goal:** write a one-page "lessons learned" note.

### Skill-building tracks

| Goal                                 | Where to start                                                | Practice exercise                                                                |
| ------------------------------------ | ------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| **Become a better leader**           | Leadership, command policy and personnel-related publications | Write your own one-page "roles and responsibilities" for a team you belong to.   |
| **Improve writing**                  | Any instruction or handbook                                   | Rewrite a dense paragraph in plain language, then compare it with the original.  |
| **Learn project discipline**         | Planning, acquisition and program-related publications        | Create a project plan with objectives, owners, milestones and review points.     |
| **Learn safety thinking**            | Safety-related publications                                   | Do a risk assessment of a household or workplace activity using a simple matrix. |
| **Learn cyber hygiene**              | Information, communications and cyber-related publications    | Audit your own passwords, backups, updates and account recovery options.         |
| **Learn health and wellness habits** | Health and wellness related publications                      | Write a personal wellness plan and review it monthly.                            |
| **Learn research skills**            | Any document with references                                  | Build a bibliography and a reference map from one publication.                   |
| **Learn data skills**                | All PDFs                                                      | Extract text, count terms, visualize topics (see developer section).             |

### Active-learning techniques

- **Teach it back:** explain a chapter to a friend in 5 minutes.
- **Make flashcards:** terms, acronyms and definitions.
- **Create a one-page cheat sheet** for each publication you finish.
- **Quiz yourself:** write 10 questions after reading, answer them a week later.
- **Compare versions:** see what changed between an older and a newer edition.

### Track your progress

Keep a simple log:

```markdown
| Date | Publication | Time spent | Key takeaway | Next action |
| ---- | ----------- | ---------- | ------------ | ----------- |
|      |             |            |              |             |
```

---

## 🤲 How to Improve Your Community with These Docs

1. **Start a reading circle.** Pick one short publication per month and discuss it.
2. **Host a workshop.** Teach "How to write a clear SOP" using a government publication as the example.
3. **Build a preparedness plan.** Use safety and emergency-related structure to write a neighborhood or club plan.
4. **Create a mentoring program.** Pair experienced people with newcomers and use handbooks as discussion material.
5. **Offer free tutoring.** Help students use primary sources in essays and research projects.
6. **Digitize and translate explanations.** Write plain-language summaries (not translations of official text) so more people can understand the ideas.
7. **Support veterans and military families.** Help them locate and understand official guidance, and always point them to the official source for final answers.
8. **Make a local resource library.** Share this repository link at libraries, schools and community centers.
9. **Run a data-science meetup.** Teach text mining and search using these PDFs as a shared dataset.
10. **Adopt good documentation habits.** Introduce numbered requirements, roles, glossaries and review dates in local organizations.

---

## 🌍 How Anyone Can Use This Library

You do **not** need military experience, special software or technical skills.

| If you are...                     | Do this                                                                       |
| --------------------------------- | ----------------------------------------------------------------------------- |
| **A complete beginner**           | Download one PDF, read the first chapter, and write a 3-sentence summary.     |
| **A student**                     | Use the documents as primary sources and cite them correctly.                 |
| **A teacher**                     | Assign a short section and ask students to identify purpose, roles and steps. |
| **A parent or guardian**          | Explore career, education and wellness information together with your child.  |
| **A job seeker**                  | Learn terminology and organization structure before applying or interviewing. |
| **A writer or journalist**        | Verify facts against primary sources and cite precisely.                      |
| **A developer**                   | Build search, summarization and analysis tools (see below).                   |
| **A researcher**                  | Build datasets, track changes and run text analysis.                          |
| **A librarian**                   | Add the collection to a resource guide.                                       |
| **A community leader**            | Borrow structure and clarity for local policies and plans.                    |
| **Someone with limited internet** | Download the ZIP once and read offline.                                       |
| **Someone using a phone**         | Open PDFs directly in your phone's browser or a free PDF app.                 |

**Accessibility tips**

- Use your device's **text-to-speech** to listen to PDFs.
- Increase font size or use a **reader mode** if available.
- Use a screen reader on tagged PDFs.
- Use **OCR tools** if a PDF is a scanned image rather than text.

---

## 🧠 Using the PDFs with AI Tools

### Option 1: Upload a PDF to an AI assistant

Upload one document and ask:

```text
Summarize this publication in 10 bullet points.
List every role named in the document and what each one is responsible for.
Create 15 flashcards from the definitions in this document.
Explain Chapter 2 as if I were a high school student.
What other publications does this document reference?
```

### Option 2: Build your own retrieval system (RAG)

**High-level pipeline**

```text
PDF files  ->  Text extraction  ->  Cleaning  ->  Chunking  ->  Embeddings
                                                         |
                                                         v
                                              Vector database  <-  User question
                                                         |
                                                         v
                                        Top matching chunks + question -> LLM -> Answer with citations
```

**Best practices**

- Keep **publication number, title, date, chapter and page** as metadata on every chunk.
- Always return **citations** (file name and page) with every answer.
- Re-run extraction when a publication is updated.
- Test with questions you already know the answers to.
- Never present generated answers as official guidance.

### Option 3: Batch processing

Process all PDFs to create a **CSV or JSON index** of titles, numbers, dates and page counts for easy searching.

---

## 🗓️ Sample 12-Week Study Plans

### Plan A: "Leadership and Communication" (beginner)

| Week | Focus                           | Activity                                                 |
| ---- | ------------------------------- | -------------------------------------------------------- |
| 1    | Learn the publication hierarchy | Read this README; identify one example of each type.     |
| 2    | Read a handbook                 | Summarize in one page.                                   |
| 3    | Roles and responsibilities      | Map who does what in one publication.                    |
| 4    | Writing style                   | Rewrite one section in plain language.                   |
| 5    | Personnel and development       | Read one chapter; write a development plan for yourself. |
| 6    | Mid-point review                | Quiz yourself; make flashcards.                          |
| 7    | Checklists                      | Create a checklist from one publication.                 |
| 8    | Safety basics                   | Do a personal risk assessment.                           |
| 9    | Communication                   | Draft a one-page policy for a club or team.              |
| 10   | Feedback                        | Share your draft; ask for edits.                         |
| 11   | Revision                        | Improve based on feedback.                               |
| 12   | Present                         | Give a 10-minute talk to a group.                        |

### Plan B: "AI and Document Analysis" (intermediate/advanced)

| Week | Focus       | Activity                                                    |
| ---- | ----------- | ----------------------------------------------------------- |
| 1    | Setup       | Install Python and PDF libraries; clone repo.               |
| 2    | Extraction  | Extract text from 10 PDFs; handle errors.                   |
| 3    | Cleaning    | Remove headers, footers, page numbers.                      |
| 4    | Metadata    | Build a CSV index (number, title, date, pages).             |
| 5    | Exploration | Word frequencies, top terms, charts.                        |
| 6    | Acronyms    | Extract acronyms and definitions.                           |
| 7    | Chunking    | Split text into overlapping chunks with metadata.           |
| 8    | Embeddings  | Create embeddings and a searchable index.                   |
| 9    | Retrieval   | Build a simple question-answering prototype with citations. |
| 10   | Evaluation  | Write 30 test questions; measure accuracy.                  |
| 11   | Graph       | Build a reference graph between publications.               |
| 12   | Share       | Publish your notebook and write a short report.             |

---

## 💻 Quick Start for Developers

### Setup

```bash
# Clone the repository
git clone https://github.com/PrajwalKoirala638/e-publishing-af-mil-documentation.git
cd e-publishing-af-mil-documentation

# Create a virtual environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# Install helpful libraries
pip install pypdf pdfplumber pandas
```

### Extract text from every PDF

```python
# Import the standard library module for working with file paths
from pathlib import Path
# Import the PDF reader class from pypdf
from pypdf import PdfReader

# Define the folder that holds all the PDFs
pdf_dir = Path("PDFs")
# Define the folder where extracted text files will be saved
out_dir = Path("text")
# Create the output folder if it does not exist yet
out_dir.mkdir(exist_ok=True)

# Loop through every PDF file in the folder and its subfolders
for pdf_path in pdf_dir.rglob("*.pdf"):
    # Try to process the file and handle any problems safely
    try:
        # Open the PDF with the reader
        reader = PdfReader(str(pdf_path))
        # Extract the text from each page and join it with blank lines
        text = "\n\n".join((page.extract_text() or "") for page in reader.pages)
        # Build the output file path using the PDF's name
        out_file = out_dir / (pdf_path.stem + ".txt")
        # Write the extracted text to the output file as UTF-8
        out_file.write_text(text, encoding="utf-8")
        # Print a success message for this file
        print(f"OK: {pdf_path.name} ({len(reader.pages)} pages)")
    # If anything goes wrong, report the error and continue
    except Exception as err:
        # Print which file failed and why
        print(f"FAILED: {pdf_path.name} -> {err}")
```

### Build a simple metadata index

```python
# Import the standard library module for working with file paths
from pathlib import Path
# Import pandas to build and save a table
import pandas as pd
# Import the PDF reader class from pypdf
from pypdf import PdfReader

# Create an empty list that will hold one record per PDF
rows = []
# Loop through every PDF in the PDFs folder
for pdf_path in Path("PDFs").rglob("*.pdf"):
    # Try to read the file and record its details
    try:
        # Open the PDF
        reader = PdfReader(str(pdf_path))
        # Add a record with the file name, page count and size in kilobytes
        rows.append({
            # Store the file name
            "file": pdf_path.name,
            # Store the number of pages
            "pages": len(reader.pages),
            # Store the file size in kilobytes, rounded to one decimal
            "size_kb": round(pdf_path.stat().st_size / 1024, 1),
        })
    # If the file cannot be read, record it as unreadable
    except Exception:
        # Add a record showing the file could not be read
        rows.append({"file": pdf_path.name, "pages": None, "size_kb": None})

# Convert the list of records to a table and save it as CSV
pd.DataFrame(rows).to_csv("index.csv", index=False)
# Tell the user the index was created
print("Wrote index.csv")
```

### Find acronyms

```python
# Import the regular expressions module
import re
# Import the standard library module for working with file paths
from pathlib import Path
# Import Counter to count how often each acronym appears
from collections import Counter

# Create a counter to hold acronym totals
counts = Counter()
# Loop through every extracted text file
for txt in Path("text").glob("*.txt"):
    # Read the file's contents
    content = txt.read_text(encoding="utf-8", errors="ignore")
    # Find words made of 2 to 8 capital letters, which are likely acronyms
    counts.update(re.findall(r"\b[A-Z]{2,8}\b", content))

# Print the 25 most common acronyms with their counts
for acronym, n in counts.most_common(25):
    # Show each acronym and how many times it appears
    print(f"{acronym}: {n}")
```

### Search with command-line tools

```bash
# Count PDFs in the library
find PDFs -name "*.pdf" | wc -l

# Total size of the library
du -sh PDFs

# Search extracted text for a phrase
grep -rin "risk management" text/
```

---

## 🔄 Keeping the Library Up to Date

Publications are **revised, superseded and rescinded** over time. To keep this collection useful:

1. **Record the download date** for each file (in file name, a CSV index or a changelog).
2. **Check the official site** periodically for newer versions.
3. **Replace outdated files** and note what changed.
4. **Keep a `CHANGELOG.md`** with entries such as:

```markdown
## 2026-11-01

- Added: [publication number] (new)
- Updated: [publication number] (replaced earlier version)
- Removed: [publication number] (rescinded)
```

5. **Use consistent file naming**, for example:

```text
DAFI36-2670_2024-01-15.pdf
```

---

## 🤝 Contributing

Contributions are welcome and appreciated.

### Ways to contribute

- Add newly released, publicly available publications.
- Replace outdated files with current versions.
- Improve folder organization.
- Add a CSV or JSON metadata index.
- Write plain-language study guides (original work, not copied text).
- Share scripts for extraction, search and analysis.
- Fix typos and improve this README.
- Report broken or corrupted files.

### How to contribute

1. **Fork** the repository.
2. **Create a branch:** `git checkout -b add-new-publications`
3. **Make changes** and commit with a clear message.
4. **Open a Pull Request** describing what you changed and where the source was found.

### Contribution rules

- Only add documents that are **publicly releasable** and obtained from the **official website**.
- **Do not** add anything marked restricted, controlled, for official use only, or with limited distribution.
- **Do not** add personal data, passwords, or private files.
- Keep **file names clear** and consistent.
- Include the **source URL** in your pull request.

---

## 🛡️ Responsible Use and Safety

- **Check distribution statements.** Some publications carry distribution or handling markings. Only share what is cleared for public release.
- **Do not misrepresent** yourself or this repository as an official government source.
- **Do not use these documents to impersonate** personnel, forge forms or deceive others.
- **Protect personal information.** Forms may ask for sensitive data: never upload completed forms with real personal details.
- **Follow your own organization's rules.** If you are service member, civilian employee or contractor, follow your command's guidance and the official, current publications.
- **Be careful with AI.** AI tools can summarize incorrectly. Verify against the original.
- **Respect the law.** Follow all applicable laws and regulations in your country.

---

## ⚖️ Licensing and Legal Notes

- **Repository content created by the maintainer** (README, scripts, organization) is released under the **MIT License** (see `LICENSE`).
- **U.S. government publications** are generally works of the U.S. government and are commonly not subject to copyright in the United States. However, individual documents may include **third-party material, images or markings** with different terms. Review each document if you plan to reuse it commercially or redistribute widely.
- **Forms and logos** may have usage guidelines. Do not use official insignia in a way that suggests endorsement.
- This repository makes **no claim of ownership** over the original publications.

> This section is general information, not legal advice. If you have a specific legal question, consult a qualified professional.

---

## ❓ Frequently Asked Questions

**Is this an official Air Force website?**
No. It is an independent, community-maintained collection. The official source is <https://www.e-publishing.af.mil/>.

**Are these documents free?**
Yes, publicly released publications are available at no cost.

**Do I need to be in the military to read them?**
No. Anyone can read publicly releasable documents.

**Are these documents up to date?**
Not necessarily. Publications change. Always confirm the current version on the official site.

**Can I use them for school projects?**
Yes. Cite the publication number, title, date and source.

**Can I use them to train or test AI models?**
You can use them for study, prototypes, retrieval and analysis. Check each document's markings and applicable laws, and do not present AI output as official guidance.

**Can I share the PDFs?**
If the documents are cleared for public release, sharing is generally fine. Respect any markings and the official site's terms.

**A PDF will not open. What should I do?**
Try another PDF reader, re-download the file, or report the issue in the repository's Issues tab.

**The PDF is a scan and I cannot search it. What can I do?**
Run OCR with a tool such as `ocrmypdf`.

**How do I find a specific topic?**
Search file names, use `pdfgrep` on the folder, or build a text index with the scripts above.

**How can I support the project?**
Star the repository, share it, contribute updates, and report problems.

---

## 📖 Glossary

| Term                  | Meaning                                                                                   |
| --------------------- | ----------------------------------------------------------------------------------------- |
| **AFI / DAFI**        | (Department of the) Air Force Instruction: directive guidance on how to implement policy. |
| **AFMAN / DAFMAN**    | Manual: detailed procedures.                                                              |
| **AFPD / DAFPD**      | Policy Directive: high-level statement of policy.                                         |
| **AFPAM / DAFPAM**    | Pamphlet: informational guidance.                                                         |
| **AFH / DAFH**        | Handbook: practical reference.                                                            |
| **AFGM / DAFGM**      | Guidance Memorandum: immediate guidance changes.                                          |
| **OPR**               | Office of Primary Responsibility: the office that owns a publication.                     |
| **Supersedes**        | Replaces an earlier version.                                                              |
| **Rescinded**         | Officially cancelled.                                                                     |
| **Certified current** | Reviewed and confirmed as still valid.                                                    |
| **SOP**               | Standard Operating Procedure.                                                             |
| **RAG**               | Retrieval-Augmented Generation: AI answers grounded in retrieved documents.               |
| **OCR**               | Optical Character Recognition: turning scanned images into searchable text.               |
| **Embedding**         | A numeric representation of text used for semantic search.                                |
| **Chunking**          | Splitting long text into smaller pieces for processing.                                   |
| **Metadata**          | Data about data (number, title, date, source).                                            |

---

## 📌 Disclaimer

This repository is provided **"as is"** for educational and informational purposes. It is **not** affiliated with, endorsed by, or sponsored by the U.S. Air Force, the Department of the Air Force or the Department of Defense. Publications may be outdated, incomplete or superseded. **Always verify information with the official source before relying on it.** The maintainer and contributors are not responsible for decisions made using these materials.

---

## ⭐ Final Words

Knowledge is most valuable when it is shared. Whether you are a student writing your first research paper, a developer building a search tool, a teacher planning a lesson, or a community leader writing your first policy, these documents can help you **learn, build and lead**.

**Download one. Read one chapter. Write three sentences. Share what you learned.** 🚀

If this library helped you, please ⭐ **star the repository** and share it with someone who can benefit.
