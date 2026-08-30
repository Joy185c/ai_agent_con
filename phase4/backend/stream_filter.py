import asyncio

async def filter_think_tags(async_generator):
    """
    State-machine generator that filters out `<think>...</think>` tags and their content.
    Robustly handles chunks split anywhere (e.g. `<th`, `ink>`).
    Strips leading whitespace (like newlines left after </think>) to prevent blank spaces.
    """
    in_think = False
    buffer = ""
    first_yield_done = False
    
    async for chunk in async_generator:
        buffer += chunk
        
        while buffer:
            if not in_think:
                think_idx = buffer.find("<think>")
                if think_idx != -1:
                    # Found a complete <think> start tag
                    if think_idx > 0:
                        yield_str = buffer[:think_idx]
                        if not first_yield_done:
                            yield_str = yield_str.lstrip()
                        if yield_str:
                            first_yield_done = True
                            yield yield_str
                    in_think = True
                    buffer = buffer[think_idx + 7:]
                    continue
                
                # Check for partial tags at the end of the buffer
                last_lt = buffer.rfind("<")
                if last_lt != -1 and "<think>".startswith(buffer[last_lt:]):
                    if last_lt > 0:
                        yield_str = buffer[:last_lt]
                        if not first_yield_done:
                            yield_str = yield_str.lstrip()
                        if yield_str:
                            first_yield_done = True
                            yield yield_str
                    buffer = buffer[last_lt:]
                    break # wait for more chunks
                else:
                    yield_str = buffer
                    if not first_yield_done:
                        stripped = yield_str.lstrip()
                        if stripped:
                            first_yield_done = True
                            yield stripped
                    else:
                        yield yield_str
                    buffer = ""
            
            else: # in_think == True
                end_think_idx = buffer.find("</think>")
                if end_think_idx != -1:
                    in_think = False
                    buffer = buffer[end_think_idx + 8:]
                    continue
                
                # Check for partial end tags at the end of the buffer
                last_lt = buffer.rfind("<")
                if last_lt != -1 and "</think>".startswith(buffer[last_lt:]):
                    buffer = buffer[last_lt:]
                    break # wait for more chunks
                else:
                    buffer = ""
                    
    # Flush remaining buffer at the end of the stream
    if buffer and not in_think:
        if not first_yield_done:
            stripped = buffer.lstrip()
            if stripped:
                yield stripped
        else:
            yield buffer
