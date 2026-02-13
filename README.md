# 🏺 Pottery Writer: Master of Form and Word

An automated, artistic writing system designed to craft high-quality, SEO-optimized, and emotionally engaging articles for **Livemaster (Ярмарка Мастеров)**.

Focused on **Japanese and Chinese ceramics** (Kaneo Masanao, Chawan, Raku), this system adopts the persona of a "Master" — using rich sensory language, philosophical depth (Wabi-sabi, Zen), and strict technical adherence to the platform's requirements.

## 🚀 Features

-   **✍️ Artistic Persona**: Writes not just text, but "sculpts" stories using tactile and visual language.
-   **🔍 SEO-First**: Automatically generates H1, SEO Titles, Descriptions, and selects correct Rubric codes.
-   **🎨 Image Prompting**: Analyzes text to suggest "juicy", textural visuals and captions.
-   **🛡️ Quality Control**: Built-in "Critic" agent that rates "Juiciness" and "Novelty" before finalizing.
-   **🧱 Modular Workflow**: Step-by-step generation from Hook to Conclusion to Final Polish.

## 📂 System Structure

```
article-pottery-master/
├── .gemini/
│   ├── commands/                  # 🤖 Agents (Slash Commands)
│   │   ├── article-searcher.toml  # /article-searcher
│   │   ├── write-hook.toml        # /write-hook
│   │   ├── write-body.toml        # /write-body
│   │   ├── write-conclusion.toml  # /write-conclusion
│   │   ├── find-images.toml       # /find-images
│   │   ├── assemble.toml          # /assemble
│   │   ├── critique.toml          # /critique
│   │   └── finalize.toml          # /finalize
│   └── workflows/                 # 📜 Detailed Instructions
├── input/
│   └── topic.txt                  # Your article topic
├── sections/                      # 🧩 Generated Parts
│   ├── research_materials.md      # 🔍 Cultural/Technical context
│   ├── 01_hook.md
│   ├── 02_body.md
│   ├── 03_conclusion.md
│   └── images.md
├── DRAFT_ARTICLE.md               # 📝 Assembled Draft
├── review/
│   └── feedback.json              # 🧐 Critique Report
├── AUTOR_STYLE.md                 # 🎭 Full Style Guide
├── AUTOR_STYLE_QUICK_REF.md       # ⚡ Quick Style Checklist
├── FINAL_POST.md                  # ✨ Ready-to-Publish Article
└── PUBLICATION_META.md            # 📋 Metadata for Livemaster Form
```

## 🛠 Prerequisites

-   **Gemini CLI**: This project is built to run on the Gemini CLI environment.
-   **Topic**: A clear idea of what you want to write about (e.g., "Raku firing techniques", "The philosophy of the tea bowl").

## 📖 How to Use

### 1. Set the Topic
Create a file at `input/topic.txt` with your subject.
```bash
echo "Японские чаши Тяван и философия Ваби-Саби" > input/topic.txt
```

### 2. Run the Workflow
Execute the commands sequentially to build the article.

**Step 0: Research**
The "Cultural Archeologist" digs deep into Japanese/Chinese sources.
```bash
gemini /article-searcher
```

**Step 1: The Hook**
Generates the Title, SEO data, and the sensory opening.
```bash
gemini /write-hook
```

**Step 2: The Body**
Writes the main content, diving into history, technique, and aesthetics.
```bash
gemini /write-body
```

**Step 3: The Conclusion**
Adds the emotional summary and Call to Action.
```bash
gemini /write-conclusion
```

**Step 4: Visuals**
Finds or generates prompts for images to accompany the text.
```bash
gemini /find-images
```

**Step 5: Assembly**
Stitches everything together into a draft.
```bash
gemini /assemble
```

**Step 6: Critique**
The "Gallery Curator" reviews the draft for style and SEO.
```bash
gemini /critique
```

**Step 7: Final Polish**
Applies fixes and produces the final article and publication metadata.
```bash
gemini /finalize
```

### 3. Publish
Open `FINAL_POST.md`, copy the content, and paste it into the Livemaster editor.

## 🎭 The Persona: "Master of Form and Word"

The system is tuned to avoid dry, encyclopedic language. Instead of:
> *"This bowl is made of clay and fired at 1200 degrees."*

It writes:
> *"This bowl was born from the rough earth, tempered by a fire that remembers the breath of the kiln..."*

See `AUTOR_STYLE.md` for the full style guide.

## 🔧 Customization

-   **Style**: Edit `AUTOR_STYLE.md` to tweak the voice.
-   **Workflow**: Modify files in `.gemini/workflows/` to change specific agent behaviors.

---
*Created for the true connoisseurs of ceramics.*
