"""
DeepSeek API client for generating C++ code revisions.

Uses the OpenAI-compatible API to call DeepSeek models for automated
code quality improvements based on linter feedback.

Environment variables:
    DEEPSEEK_API_KEY  (required) - API key for DeepSeek
    DEEPSEEK_BASE_URL (optional) - API base URL, default: https://chat.noc.pku.edu.cn/v1
    DEEPSEEK_MODEL    (optional) - Model name, default: deepseek-v3.2-128k
"""

import json
import logging
import os
import sys
import time
from pathlib import Path

from openai import OpenAI, APIConnectionError, APIStatusError, APITimeoutError

# ---------------------------------------------------------------------------
# Make sibling modules importable regardless of how this file is invoked.
# ---------------------------------------------------------------------------
_THIS_DIR = Path(__file__).resolve().parent
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

from prompt_templates import build_revision_prompt  # noqa: E402
from utils import extract_code_from_response          # noqa: E402

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default configuration
# ---------------------------------------------------------------------------
_DEFAULT_BASE_URL = "https://chat.noc.pku.edu.cn/v1"
_DEFAULT_MODEL = "deepseek-v3.2-128k"


# ===========================================================================
# DeepSeekReviser
# ===========================================================================
class DeepSeekReviser:
    """Client that calls DeepSeek to revise C++ code based on linter messages."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 8192,
        max_retries: int = 3,
        retry_delay: float = 5.0,
    ):
        # ---- Resolve configuration from args / env vars ------------------
        self.api_key = api_key or os.environ.get("DEEPSEEK_API_KEY")
        if not self.api_key:
            raise ValueError(
                "DeepSeek API key is required.  Pass api_key=... or set the "
                "DEEPSEEK_API_KEY environment variable."
            )

        self.base_url = base_url or os.environ.get(
            "DEEPSEEK_BASE_URL", _DEFAULT_BASE_URL
        )
        self.model = model or os.environ.get("DEEPSEEK_MODEL", _DEFAULT_MODEL)
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.max_retries = max_retries
        self.retry_delay = retry_delay

        # ---- Initialise the OpenAI-compatible client ---------------------
        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=120.0,           # generous read timeout
            max_retries=0,           # we handle retries ourselves
        )

        logger.info(
            "DeepSeekReviser initialised  model=%s  base_url=%s",
            self.model,
            self.base_url,
        )

    # ------------------------------------------------------------------
    # Single-sample revision
    # ------------------------------------------------------------------
    def generate_revision(self, code: str, linter_messages: list, language: str = "cpp") -> dict:
        """Send a single code-revision request to DeepSeek.

        Parameters
        ----------
        code : str
            The original source code.
        linter_messages : list
            A list of structured linter diagnostic dicts.
        language : str
            Source language ('cpp', 'py3', 'java').

        Returns
        -------
        dict
            {
                "revised_code": str | None,
                "raw_response": str,
                "tokens_used": int,
                "error": str | None,
            }
        """
        prompt = build_revision_prompt(code, linter_messages, language=language)

        last_error: str | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                logger.debug(
                    "Attempt %d/%d  model=%s", attempt, self.max_retries, self.model
                )
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=prompt,
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                )

                raw_response = response.choices[0].message.content or ""
                tokens_used = 0
                if response.usage:
                    tokens_used = response.usage.total_tokens

                # Try to extract just the code from the model's response.
                revised_code = extract_code_from_response(raw_response)
                if revised_code is None:
                    logger.warning(
                        "Could not extract code from response (attempt %d).  "
                        "Using raw response as fallback.",
                        attempt,
                    )
                    # Keep raw_response in the dict so the caller can inspect it,
                    # but report a soft error.
                    return {
                        "revised_code": raw_response,
                        "raw_response": raw_response,
                        "tokens_used": tokens_used,
                        "error": "code_extraction_failure: no C++ code block found",
                    }

                return {
                    "revised_code": revised_code,
                    "raw_response": raw_response,
                    "tokens_used": tokens_used,
                    "error": None,
                }

            except APIStatusError as exc:
                # ---- Rate-limit handling --------------------------------
                if exc.status_code == 429:
                    wait = self.retry_delay * attempt
                    logger.warning(
                        "Rate-limited (429).  Waiting %.1fs before retry %d/%d.",
                        wait,
                        attempt,
                        self.max_retries,
                    )
                    time.sleep(wait)
                    last_error = f"rate_limited (429): {exc.message}"
                    continue

                # ---- Other HTTP errors ----------------------------------
                last_error = (
                    f"API_status_error (HTTP {exc.status_code}): {exc.message}"
                )
                logger.error(last_error)
                if attempt < self.max_retries:
                    time.sleep(self.retry_delay)

            except APIConnectionError as exc:
                last_error = f"API_connection_error: {exc}"
                logger.error(
                    "Connection error (attempt %d/%d): %s",
                    attempt,
                    self.max_retries,
                    exc,
                )
                if attempt < self.max_retries:
                    time.sleep(self.retry_delay)

            except APITimeoutError as exc:
                last_error = f"API_timeout_error: {exc}"
                logger.error(
                    "Timeout (attempt %d/%d): %s",
                    attempt,
                    self.max_retries,
                    exc,
                )
                if attempt < self.max_retries:
                    time.sleep(self.retry_delay)

            except Exception as exc:  # pylint: disable=broad-except
                last_error = f"unexpected_error: {type(exc).__name__}: {exc}"
                logger.error(
                    "Unexpected error (attempt %d/%d): %s",
                    attempt,
                    self.max_retries,
                    exc,
                    exc_info=True,
                )
                if attempt < self.max_retries:
                    time.sleep(self.retry_delay)

        # All retries exhausted.
        return {
            "revised_code": None,
            "raw_response": "",
            "tokens_used": 0,
            "error": f"all_retries_exhausted: {last_error}",
        }

    # ------------------------------------------------------------------
    # Batch processing with checkpoint / resume + threaded concurrency
    # ------------------------------------------------------------------
    def generate_batch(self, samples: list, output_path: str, n_workers: int = 8) -> list:
        """Process a batch of samples, writing results to a JSONL file.

        Each *sample* in ``samples`` must be a dict with at least:
            - ``"code"``  (str)           - the original source
            - ``"linter_messages"`` (list) - list of linter diagnostic dicts

        Any extra keys in the sample dict are carried through to the output
        record unchanged.

        Results are **appended** to ``output_path`` in JSONL format (one JSON
        object per line).  Samples whose ``"id"`` (or ``"source" + "_" +
        "id"``) already appears in the file are **skipped**, enabling simple
        checkpoint / resume.

        Uses ThreadPoolExecutor for concurrent API calls (I/O-bound).

        Parameters
        ----------
        samples : list[dict]
            List of sample dicts.
        output_path : str
            Path to the JSONL output file.
        n_workers : int
            Number of concurrent API calls (default: 8).

        Returns
        -------
        list[dict]
            The full list of result records (one per sample).
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed
        import threading

        output_path = str(output_path)
        results: list[dict] = []
        write_lock = threading.Lock()

        # ---- Load already-processed IDs for resume support ---------------
        completed_ids: set[str] = set()
        if os.path.isfile(output_path):
            with open(output_path, "r", encoding="utf-8") as fin:
                for line in fin:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                        rid = self._sample_id(rec)
                        if rid:
                            completed_ids.add(rid)
                        results.append(rec)
                    except json.JSONDecodeError:
                        logger.warning("Skipping malformed line in %s", output_path)
            logger.info(
                "Resumed from %s  (%d completed samples).", output_path, len(completed_ids)
            )

        # Filter out already-done samples
        todo = []
        for sample in samples:
            sample_key = self._sample_id(sample)
            if sample_key and sample_key in completed_ids:
                continue
            todo.append(sample)

        logger.info("Processing %d samples with %d workers", len(todo), n_workers)

        # ---- Open file in append mode for incremental writes -------------
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        fout = open(output_path, "a", encoding="utf-8")
        completed_count = 0
        total_tokens = 0

        def process_one(sample):
            nonlocal completed_count, total_tokens
            sample_key = self._sample_id(sample)
            code = sample.get("code", "")
            linter_messages = sample.get("linter_messages", [])
            language = sample.get("language", "cpp")

            if not code:
                result = {
                    **sample,
                    "revised_code": None,
                    "raw_response": "",
                    "tokens_used": 0,
                    "error": "skipped: empty source code",
                }
            else:
                revision = self.generate_revision(code, linter_messages, language=language)
                result = {
                    **sample,
                    "revised_code": revision["revised_code"],
                    "raw_response": revision["raw_response"],
                    "tokens_used": revision["tokens_used"],
                    "error": revision["error"],
                }

            with write_lock:
                results.append(result)
                fout.write(json.dumps(result, ensure_ascii=False) + "\n")
                fout.flush()
                completed_count += 1
                total_tokens += result.get("tokens_used", 0)
                if completed_count % 10 == 0:
                    logger.info(
                        "Progress: %d / %d  total_tokens=%d  errors=%d",
                        completed_count, len(todo), total_tokens,
                        sum(1 for r in results if r.get("error")),
                    )
                if result.get("error"):
                    logger.warning(
                        "Sample %s error: %s", sample_key, result["error"]
                    )

            return result

        with ThreadPoolExecutor(max_workers=n_workers) as pool:
            futures = [pool.submit(process_one, s) for s in todo]
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as exc:
                    logger.error("Worker error: %s", exc)

        fout.close()
        logger.info(
            "Batch complete.  %d results written to %s", len(results), output_path
        )
        return results

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _sample_id(sample: dict) -> str:
        """Derive a stable identifier from a sample dict.

        Looks for ``"id"`` first, then ``"source" + "_" + "id"``, and
        finally falls back to ``""`` (empty string).
        """
        if "id" in sample and sample["id"]:
            if "source" in sample and sample["source"]:
                return f"{sample['source']}_{sample['id']}"
            return str(sample["id"])
        return ""
