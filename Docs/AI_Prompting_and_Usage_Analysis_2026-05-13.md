# GutenDocx AI Prompting and Usage Analysis

**Date:** 2026-05-13
**Default model remains:** `gpt-4o-mini`

## Local OpenAI Guides Snapshot

Official OpenAI guidance saved locally under `Docs/OpenAI_Guides/`:

- `prompting.md`: general prompt lifecycle, prompt versioning, evals, and prompt caching.
- `reasoning-best-practices.md`: when to use reasoning models and how their prompts differ from GPT/non-reasoning models.
- `latest-model.md`: GPT-5.5 migration and model-family guidance.
- `prompt-guidance.md`: GPT-5.5 prompt guidance.
- `gpt4-1_prompting_guide.ipynb` and `gpt4-1_prompting_guide.md`: GPT-4.1 prompting guide from OpenAI Cookbook.
- `gpt-5_prompting_guide.ipynb` and `gpt-5_prompting_guide.md`: GPT-5 prompting guide from OpenAI Cookbook.
- `gpt-5-1_prompting_guide.ipynb` and `gpt-5-1_prompting_guide.md`: GPT-5.1 prompting guide from OpenAI Cookbook.

These are reference snapshots for future prompt/model work. Refresh them before a major model migration because OpenAI guidance and pricing can change.

## Current AI Usage Map

GutenDocx currently uses AI in two core places:

1. **Cover vision detection**
   - Code: `gutendocx/core/vision.py::detect_cover_roles_vision`.
   - Call path: `run_cover_pipeline(..., vision=True)`.
   - Purpose: render page 1 and identify visual cover roles: title, subtitle, author.
   - Current prompt asks for strict JSON with role, bbox, confidence, and readable text.
   - This is justified when learning/applying cover styles or when cover metadata is needed for reports.

2. **Body style learning**
   - Code: `gutendocx/core/body_vision.py::detect_body_styles_vision`.
   - Call path: `/config/learn_body_styles`.
   - Purpose: combine a full style inventory with rendered pages and classify styles as heading1, heading2, heading3, heading4, body, or ignore.
   - Current prompt explicitly says to classify by samples/usage rather than style names.
   - This is justified during learning because Gutenberg/Word documents often use custom style names that cannot be mapped safely by heuristics alone.

Normal whole-document style application does not need AI after the relevant style mapping/settings have been learned. It applies the configured template/mapping deterministically.

## Current Prompt Assessment

For the current default `gpt-4o-mini`, both prompts are broadly aligned with general GPT prompt guidance:

- They give a specific task.
- They define the allowed output shape.
- They constrain roles/labels.
- They include negative instructions such as not inventing absent subtitles or style names.
- Body learning includes examples and a concrete classification target.

Potential prompt/API improvements to discuss before changing:

1. **Use structured outputs where supported**
   - Instead of relying on "Return JSON" plus regex/`json.loads`, use API-level schema validation where supported.
   - Expected benefit: fewer malformed responses and less brittle parsing.
   - Risk: requires compatibility testing across `gpt-4o-mini`, GPT-4.1, GPT-5, and GPT-5.4/5.5 family models.

2. **Separate model-family prompt variants**
   - GPT/non-reasoning models such as `gpt-4o-mini` and GPT-4.1 benefit from explicit instructions and examples.
   - GPT-5 reasoning-family models may need more attention to `reasoning.effort`, `text.verbosity`, concise outcome-first prompts, and avoiding unnecessary step-by-step instructions.
   - If we support multiple model families in the UI, a prompt registry keyed by model family may be better than one prompt string for all models.

3. **Prompt caching**
   - The body-style prompt contains a stable instruction block and a dynamic style inventory.
   - If moving to Responses API and if the prompt is large enough/repeated enough, put stable instructions first and dynamic document data last to improve cache hit potential.

4. **Do not change default model yet**
   - `gpt-4o-mini` remains a reasonable default for the current vision/classification workload.
   - Newer models should be benchmarked against representative DOCX files before replacing the default.
   - Google `gemini-2.5-flash-lite` should be included as a future A/B test candidate for vision/classification because current Google pricing suggests it may be cheaper for image/text input, but it needs provider-abstraction work and quality validation before any production use.

## Model-Family Differences Relevant To GutenDocx

- `gpt-4o-mini`: good low-cost baseline for focused visual/text classification. Use explicit prompts and examples.
- GPT-4.1 family: stronger literal instruction following and long-context behavior. Prompts should be precise because the model follows instructions closely.
- GPT-5 family: reasoning and verbosity controls matter. For low-latency classification, start with low/minimal/none-style reasoning only after API compatibility is verified.
- GPT-5.4/5.5 family: not a drop-in replacement. OpenAI guidance recommends fresh baselines, explicit success criteria, output shape, reasoning/verbosity tuning, and evals.

For GutenDocx, the prompt differences are likely meaningful only if we move from `gpt-4o-mini` to GPT-5-family reasoning models. A model-family prompt registry is worth considering before serious multi-model support.

## AI Optimization Questions

Quality remains higher priority than token cost, but logs show several optimization candidates:

1. **Batch report cover dry-run**
   - Resolved on 2026-05-13.
   - Body-only batch `/apply` no longer runs AI cover dry-run just to populate XLSX report title/subtitle/author metadata.
   - If `apply_cover=false`, report cover metadata may be blank, but DOCX/PDF style output remains deterministic and avoids unnecessary per-file AI calls.
   - QA baseline used `Simples/pg69954.docx`: before change, body-only batch spent 25,619 input tokens / 245 output tokens (`$0.00398985`) for `cover_vision_dry_run`; after change, AI cost was zero, PDF page count stayed 306, and DOCX paragraph/style/text signatures matched.

2. **Repeated processing after Cloudflare timeout**
   - A user can click Apply again after a visible timeout while the server is still processing the first request.
   - That can duplicate AI calls for the same batch.
   - Recommendation: background job state should prevent duplicate concurrent processing of the same batch.

3. **Learning once vs applying many**
   - AI is valuable during Learn Body Styles and Learn Cover Styles.
   - Applying a learned template to many files should be deterministic where possible.
   - Exception: if each file has materially different styles/cover structures and the report depends on per-file cover metadata, per-file AI analysis may still be justified.

4. **Cover vs body independence**
   - Body-only processing should not require cover AI unless report metadata needs it.
   - Cover processing correctly needs cover AI or heuristic fallback.

## Cloudflare Timeout Explanation

The production path is:

`browser -> Cloudflare Access/Tunnel -> FastAPI on 127.0.0.1:8000`

Cloudflare is not doing the document processing. It is the secure public doorway. The timeout happens because the browser request stays open while the server processes many DOCX files synchronously. For a large batch, processing can take several minutes; Cloudflare eventually stops waiting and returns `HTTP 524`, even though the local server may continue and finish the ZIP.

The current `/batch/status/{batch_id}` polling is a recovery mechanism: after timeout, the UI can discover that the ZIP became ready.

The more correct architecture is a background job model:

1. Browser sends `POST /jobs` and immediately receives a `job_id`.
2. Server processes files in the background.
3. Browser polls or streams job progress.
4. Browser downloads the output when the job reaches `completed`.

This removes long open HTTP requests from the main workflow and avoids Cloudflare request timeouts as a normal user-facing condition. It is more work than the current recovery patch but is the right architecture if clients will regularly process large batches.

## Required QA Rule For Risky Changes

For important behavior changes, especially prompts, model routing, AI usage, batch orchestration, or DOCX style application:

1. Commit the current working state first, excluding incidental runtime `config.yaml` changes.
2. Define concrete tests for the target behavior and key existing behavior that must not regress.
3. Run tests before the change and record baseline outputs.
4. Make the smallest scoped change.
5. Run the same tests again.
6. Compare results: did quality improve, worsen, or remain stable; did any working path regress; were dependencies and side effects accounted for.
7. Keep the change only if benefit is clear and regression risk is acceptable. Otherwise revert or redesign.

Prompt/model changes must be discussed with the user before implementation.
