import asyncio

async def filter_think_tags(async_generator):
    """
    State-machine generator that filters out `<think>...</think>` tags and their content.
    Robustly handles chunks split anywhere (e.g. `<th`, `ink>`).
    """
    in_think = False
    buffer = ""
    
    async for chunk in async_generator:
        buffer += chunk
        
        while buffer:
            if not in_think:
                think_idx = buffer.find("<think>")
                if think_idx != -1:
                    # Found a complete <think> start tag
                    if think_idx > 0:
                        yield buffer[:think_idx]
                    in_think = True
                    buffer = buffer[think_idx + 7:]
                    continue
                
                # Check for partial tags at the end of the buffer
                last_lt = buffer.rfind("<")
                if last_lt != -1 and "<think>".startswith(buffer[last_lt:]):
                    # Could be the start of `<think>`. Yield everything before it, keep the rest in buffer.
                    if last_lt > 0:
                        yield buffer[:last_lt]
                    buffer = buffer[last_lt:]
                    break # wait for more chunks
                else:
                    # Safe to yield the whole buffer
                    yield buffer
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
                    # Could be the start of `</think>`. Keep it in buffer, discard everything before it.
                    buffer = buffer[last_lt:]
                    break # wait for more chunks
                else:
                    # Safely discard the entire reasoning chunk
                    buffer = ""
                    
    # Flush remaining buffer at the end of the stream
    if buffer and not in_think:
        yield buffer
