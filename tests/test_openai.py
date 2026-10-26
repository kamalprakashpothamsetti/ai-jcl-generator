import os
from dotenv import load_dotenv

if __name__ == "__main__":
    load_dotenv()
    from openai import OpenAI

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    response = client.responses.create(
        model=os.getenv("OPENAI_MODEL", "gpt-5.4-mini"),
        instructions=(
            "You are an IBM z/OS JCL expert. "
            "Generate sample JCL with brief explanations. "
            "Use placeholders for site-specific values."
        ),
        input=(
            "Generate a sample IEFBR14 JCL to allocate "
            "a sequential dataset with RECFM=FB and LRECL=80."
        ),
        max_output_tokens=1200
    )

    print(response.output_text)