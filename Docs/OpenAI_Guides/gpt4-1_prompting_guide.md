# GPT-4.1 Prompting Guide

The GPT-4.1 family of models represents a significant step forward from GPT-4o in capabilities across coding, instruction following, and long context. In this prompting guide, we collate a series of important prompting tips derived from extensive internal testing to help developers fully leverage the improved abilities of this new model family. 

Many typical best practices still apply to GPT-4.1, such as providing context examples, making instructions as specific and clear as possible, and inducing planning via prompting to maximize model intelligence. However, we expect that getting the most out of this model will require some prompt migration. GPT-4.1 is trained to follow instructions more closely and more literally than its predecessors, which tended to more liberally infer intent from user and system prompts. This also means, however, that GPT-4.1 is highly steerable and responsive to well-specified prompts - if model behavior is different from what you expect, a single sentence firmly and unequivocally clarifying your desired behavior is almost always sufficient to steer the model on course.

Please read on for prompt examples you can use as a reference, and remember that while this guidance is widely applicable, no advice is one-size-fits-all. AI engineering is inherently an empirical discipline, and large language models are inherently nondeterministic; in addition to following this guide, we advise building informative evals and iterating often to ensure your prompt engineering changes are yielding benefits for your use case.

# 1. Agentic Workflows

GPT-4.1 is a great place to build agentic workflows. In model training we emphasized providing a diverse range of agentic problem-solving trajectories, and our agentic harness for the model achieves state-of-the-art performance for non-reasoning models on SWE-bench Verified, solving 55% of problems. 


## System Prompt Reminders

In order to fully utilize the agentic capabilities of GPT-4.1, we recommend including three key types of reminders in all agent prompts. The following prompts are optimized specifically for the agentic coding workflow, but can be easily modified for general agentic use cases.

1. Persistence: this ensures the model understands it is entering a multi-message turn, and prevents it from prematurely yielding control back to the user. Our example is the following:

```
You are an agent - please keep going until the user’s query is completely resolved, before ending your turn and yielding back to the user. Only terminate your turn when you are sure that the problem is solved.
```

2. Tool-calling: this encourages the model to make full use of its tools, and reduces its likelihood of hallucinating or guessing an answer. Our example is the following:

```
If you are not sure about file content or codebase structure pertaining to the user’s request, use your tools to read files and gather the relevant information: do NOT guess or make up an answer.
```

3. Planning \[optional\]: if desired, this ensures the model explicitly plans and reflects upon each tool call in text, instead of completing the task by chaining together a series of only tool calls. Our example is the following:

```
You MUST plan extensively before each function call, and reflect extensively on the outcomes of the previous function calls. DO NOT do this entire process by making function calls only, as this can impair your ability to solve the problem and think insightfully.
```

GPT-4.1 is trained to respond very closely to both user instructions and system prompts in the agentic setting. The model adhered closely to these three simple instructions and increased our internal SWE-bench Verified score by close to 20% \- so we highly encourage starting any agent prompt with clear reminders covering the three categories listed above. As a whole, we find that these three instructions transform the model from a chatbot-like state into a much more “eager” agent, driving the interaction forward autonomously and independently. 

## Tool Calls

Compared to previous models, GPT-4.1 has undergone more training on effectively utilizing tools passed as arguments in an OpenAI API request. We encourage developers to exclusively use the tools field to pass tools, rather than manually injecting tool descriptions into your prompt and writing a separate parser for tool calls, as some have reported doing in the past. This is the best way to minimize errors and ensure the model remains in distribution during tool-calling trajectories \- in our own experiments, we observed a 2% increase in SWE-bench Verified pass rate when using API-parsed tool descriptions versus manually injecting the schemas into the system prompt.

Developers should name tools clearly to indicate their purpose and add a clear, detailed description in the "description" field of the tool. Similarly, for each tool param, lean on good naming and descriptions to ensure appropriate usage. If your tool is particularly complicated and you'd like to provide examples of tool usage, we recommend that you create an `# Examples` section in your system prompt and place the examples there, rather than adding them into the "description' field, which should remain thorough but relatively concise. Providing examples can be helpful to indicate when to use tools, whether to include user text alongside tool calls, and what parameters are appropriate for different inputs. Remember that you can use “Generate Anything” in the [Prompt Playground](https://platform.openai.com/playground) to get a good starting point for your new tool definitions.

## Prompting-Induced Planning & Chain-of-Thought

As mentioned already, developers can optionally prompt agents built with GPT-4.1 to plan and reflect between tool calls, instead of silently calling tools in an unbroken sequence. GPT-4.1 is not a reasoning model \- meaning that it does not produce an internal chain of thought before answering \- but in the prompt, a developer can induce the model to produce an explicit, step-by-step plan by using any variant of the Planning prompt component shown above. This can be thought of as the model “thinking out loud.” In our experimentation with the SWE-bench Verified agentic task, inducing explicit planning increased the pass rate by 4%. 

## Sample Prompt: SWE-bench Verified

Below, we share the agentic prompt that we used to achieve our highest score on SWE-bench Verified, which features detailed instructions about workflow and problem-solving strategy. This general pattern can be used for any agentic task.

# 2. Long context

GPT-4.1 has a performant 1M token input context window, and is useful for a variety of long context tasks, including structured document parsing, re-ranking, selecting relevant information while ignoring irrelevant context, and performing multi-hop reasoning using context.

## Optimal Context Size

We observe very good performance on needle-in-a-haystack evaluations up to our full 1M token context, and we’ve observed very strong performance at complex tasks with a mix of both relevant and irrelevant code and other documents. However, long context performance can degrade as more items are required to be retrieved, or perform complex reasoning that requires knowledge of the state of the entire context (like performing a graph search, for example).

## Tuning Context Reliance

Consider the mix of external vs. internal world knowledge that might be required to answer your question. Sometimes it’s important for the model to use some of its own knowledge to connect concepts or make logical jumps, while in others it’s desirable to only use provided context

```
# Instructions
// for internal knowledge
- Only use the documents in the provided External Context to answer the User Query. If you don't know the answer based on this context, you must respond "I don't have the information needed to answer that", even if a user insists on you answering the question.
// For internal and external knowledge
- By default, use the provided external context to answer the User Query, but if other basic knowledge is needed to answer, and you're confident in the answer, you can use some of your own knowledge to help answer the question.
```

## Prompt Organization

Especially in long context usage, placement of instructions and context can impact performance. If you have long context in your prompt, ideally place your instructions at both the beginning and end of the provided context, as we found this to perform better than only above or below. If you’d prefer to only have your instructions once, then above the provided context works better than below.

# 3. Chain of Thought

As mentioned above, GPT-4.1 is not a reasoning model, but prompting the model to think step by step (called “chain of thought”) can be an effective way for a model to break down problems into more manageable pieces, solve them, and improve overall output quality, with the tradeoff of higher cost and latency associated with using more output tokens. The model has been trained to perform well at agentic reasoning about and real-world problem solving, so it shouldn’t require much prompting to perform well.

We recommend starting with this basic chain-of-thought instruction at the end of your prompt:

```
...

First, think carefully step by step about what documents are needed to answer the query. Then, print out the TITLE and ID of each document. Then, format the IDs into a list.
```

From there, you should improve your chain-of-thought (CoT) prompt by auditing failures in your particular examples and evals, and addressing systematic planning and reasoning errors with more explicit instructions. In the unconstrained CoT prompt, there may be variance in the strategies it tries, and if you observe an approach that works well, you can codify that strategy in your prompt. Generally speaking, errors tend to occur from misunderstanding user intent, insufficient context gathering or analysis, or insufficient or incorrect step by step thinking, so watch out for these and try to address them with more opinionated instructions.

Here is an example prompt instructing the model to focus more methodically on analyzing user intent and considering relevant context before proceeding to answer.

```
# Reasoning Strategy
1. Query Analysis: Break down and analyze the query until you're confident about what it might be asking. Consider the provided context to help clarify any ambiguous or confusing information.
2. Context Analysis: Carefully select and analyze a large set of potentially relevant documents. Optimize for recall - it's okay if some are irrelevant, but the correct documents must be in this list, otherwise your final answer will be wrong. Analysis steps for each:
	a. Analysis: An analysis of how it may or may not be relevant to answering the query.
	b. Relevance rating: [high, medium, low, none]
3. Synthesis: summarize which documents are most relevant and why, including all documents with a relevance rating of medium or higher.

# User Question
{user_question}

# External Context
{external_context}

First, think carefully step by step about what documents are needed to answer the query, closely adhering to the provided Reasoning Strategy. Then, print out the TITLE and ID of each document. Then, format the IDs into a list.
```

# 4. Instruction Following

GPT-4.1 exhibits outstanding instruction-following performance, which developers can leverage to precisely shape and control the outputs for their particular use cases. Developers often extensively prompt for agentic reasoning steps, response tone and voice, tool calling information, output formatting, topics to avoid, and more. However, since the model follows instructions more literally, developers may need to include explicit specification around what to do or not to do. Furthermore, existing prompts optimized for other models may not immediately work with this model, because existing instructions are followed more closely and implicit rules are no longer being as strongly inferred.

## Recommended Workflow

Here is our recommended workflow for developing and debugging instructions in prompts:

1. Start with an overall “Response Rules” or “Instructions” section with high-level guidance and bullet points.  
2. If you’d like to change a more specific behavior, add a section to specify more details for that category, like `# Sample Phrases`.  
3. If there are specific steps you’d like the model to follow in its workflow, add an ordered list and instruct the model to follow these steps.
4. If behavior still isn’t working as expected:  
   1. Check for conflicting, underspecified, or wrong instructions and examples. If there are conflicting instructions, GPT-4.1 tends to follow the one closer to the end of the prompt.
   2. Add examples that demonstrate desired behavior; ensure that any important behavior demonstrated in your examples are also cited in your rules.
   3. It’s generally not necessary to use all-caps or other incentives like bribes or tips. We recommend starting without these, and only reaching for these if necessary for your particular prompt. Note that if your existing prompts include these techniques, it could cause GPT-4.1 to pay attention to it too strictly.

*Note that using your preferred AI-powered IDE can be very helpful for iterating on prompts, including checking for consistency or conflicts, adding examples, or making cohesive updates like adding an instruction and updating instructions to demonstrate that instruction.*

## Common Failure Modes

These failure modes are not unique to GPT-4.1, but we share them here for general awareness and ease of debugging.

* Instructing a model to always follow a specific behavior can occasionally induce adverse effects. For instance, if told “you must call a tool before responding to the user,” models may hallucinate tool inputs or call the tool with null values if they do not have enough information. Adding “if you don’t have enough information to call the tool, ask the user for the information you need” should mitigate this.
* When provided sample phrases, models can use those quotes verbatim and start to sound repetitive to users. Ensure you instruct the model to vary them as necessary.
* Without specific instructions, some models can be eager to provide additional prose to explain their decisions, or output more formatting in responses than may be desired. Provide instructions and potentially examples to help mitigate.

## Example Prompt: Customer Service

This demonstrates best practices for a fictional customer service agent. Observe the diversity of rules, the specificity, the use of additional sections for greater detail, and an example to demonstrate precise behavior that incorporates all prior rules.

Try running the following notebook cell - you should see both a user message and tool call, and the user message should start with a greeting, then echo back their answer, then mention they're about to call a tool. Try changing the instructions to shape the model behavior, or trying other user messages, to test instruction following performance.

# 5. General Advice

## Prompt Structure

For reference, here is a good starting point for structuring your prompts.

```
# Role and Objective

# Instructions

## Sub-categories for more detailed instructions

# Reasoning Steps

# Output Format

# Examples
## Example 1

# Context

# Final instructions and prompt to think step by step
```

Add or remove sections to suit your needs, and experiment to determine what’s optimal for your usage.

## Delimiters

Here are some general guidelines for selecting the best delimiters for your prompt. Please refer to the Long Context section for special considerations for that context type.

1. Markdown: We recommend starting here, and using markdown titles for major sections and subsections (including deeper hierarchy, to H4+). Use inline backticks or backtick blocks to precisely wrap code, and standard numbered or bulleted lists as needed.  
2. XML: These also perform well, and we have improved adherence to information in XML with this model. XML is convenient to precisely wrap a section including start and end, add metadata to the tags for additional context, and enable nesting. Here is an example of using XML tags to nest examples in an example section, with inputs and outputs for each:

```
<examples>
<example1 type="Abbreviate">
<input>San Francisco</input>
<output>- SF</output>
</example1>
</examples>
```

3. JSON is highly structured and well understood by the model particularly in coding contexts. However it can be more verbose, and require character escaping that can add overhead.

Guidance specifically for adding a large number of documents or files to input context:

* XML performed well in our long context testing.  
  * Example: `<doc id='1' title='The Fox'>The quick brown fox jumps over the lazy dog</doc>`  
* This format, proposed by Lee et al. ([ref](https://arxiv.org/pdf/2406.13121)), also performed well in our long context testing.  
  * Example: `ID: 1 | TITLE: The Fox | CONTENT: The quick brown fox jumps over the lazy dog`  
* JSON performed particularly poorly.  
  * Example: `[{'id': 1, 'title': 'The Fox', 'content': 'The quick brown fox jumped over the lazy dog'}]`

The model is trained to robustly understand structure in a variety of formats. Generally, use your judgement and think about what will provide clear information and “stand out” to the model. For example, if you’re retrieving documents that contain lots of XML, an XML-based delimiter will likely be less effective. 

## Caveats

* In some isolated cases we have observed the model being resistant to producing very long, repetitive outputs, for example, analyzing hundreds of items one by one. If this is necessary for your use case, instruct the model strongly to output this information in full, and consider breaking down the problem or using a more concise approach.  
* We have seen some rare instances of parallel tool calls being incorrect. We advise testing this, and considering setting the [parallel\_tool\_calls](https://platform.openai.com/docs/api-reference/responses/create#responses-create-parallel_tool_calls) param to false if you’re seeing issues.

# Appendix: Generating and Applying File Diffs

Developers have provided us feedback that accurate and well-formed diff generation is a critical capability to power coding-related tasks. To this end, the GPT-4.1 family features substantially improved diff capabilities relative to previous GPT models. Moreover, while GPT-4.1 has strong performance generating diffs of any format given clear instructions and examples, we open-source here one recommended diff format, on which the model has been extensively trained. We hope that in particular for developers just starting out, that this will take much of the guesswork out of creating diffs yourself. 

## Apply Patch

See the example below for a prompt that applies our recommended tool call correctly.

## Reference Implementation: apply\_patch.py

Here’s a reference implementation of the apply\_patch tool that we used as part of model training. You’ll need to make this an executable and available as \`apply\_patch\` from the shell where the model will execute commands:

## Other Effective Diff Formats

If you want to try using a different diff format, we found in testing that the SEARCH/REPLACE diff format used in Aider’s polyglot benchmark, as well as a pseudo-XML format with no internal escaping, both had high success rates.

These diff formats share two key aspects: (1) they do not use line numbers, and (2) they provide both the exact code to be replaced, and the exact code with which to replace it, with clear delimiters between the two.
