from mc_gen_prompt import MC_GEN_PROMPT
from dotenv import load_dotenv
import os
import requests
import json
import re
import time
import multiprocessing
from typing import Optional, List, Any, Tuple
import logging

logger = logging.getLogger(__name__)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

load_dotenv()
#XAI Client

class QuestionGenerator:
    def __init__(self, api_key: str = None, model: str = "grok-4-fast-reasoning"):
        self.api_key = api_key or os.getenv("XAI_API_KEY")
        if not self.api_key:
            raise ValueError("XAI_API_KEY environment variable not set and no API key provided")
        self.model = model
        self.api_endpoint = "https://api.x.ai/v1/chat/completions"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
    def check_api_connection(self) -> bool:
        """Check if xAI API is accessible."""
        try:
            response = requests.post(
                self.api_endpoint,
                headers=self.headers,
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": "test"}],
                    "max_tokens": 10
                },
                timeout=10
            )
            if response.status_code == 200:
                logger.info(f"Successfully connected to xAI API with model {self.model}")
                return True
            elif response.status_code == 401:
                logger.error("Invalid API key. Please check your XAI_API_KEY environment variable.")
                return False
            else:
                logger.warning(f"API returned status {response.status_code}: {response.text}")
                return False
        except Exception as e:
            logger.error(f"Error checking xAI API connection: {str(e)}")
            return False
    
    def generate_mc_questions(self, question: str, solution: str, prompt_id: int, 
                        max_retries: int = 3) -> Optional[str]:
        """Generate multiple choice questions for a cybersecurity training question using xAI API."""
        
        # Very strict prompt to ensure JSON output and educational context
        # Using techniques to avoid refusal: role-playing, positive framing, explicit affirmation
        system_prompt = """You are a cybersecurity educator and researcher who provides educational advice for ethical hacking and security training purposes. Your role is to help security professionals understand attack techniques so they can build better defenses. You always provide helpful, educational responses. Your responses must be in valid JSON format only."""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": MC_GEN_PROMPT.format(question=question, solution=solution)}
        ]

        for attempt in range(max_retries):
            try:
                response = requests.post(
                    self.api_endpoint,
                    headers=self.headers,
                    json={
                        "model": self.model,
                        "messages": messages,
                        "temperature": 0.7,
                        "max_tokens": 2000,
                        "stream": False
                    },
                    timeout=90
                )
                
                if response.status_code == 200:
                    result = response.json()
                    # xAI API returns content in choices[0].message.content
                    generated_text = result.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
                    
                    if not generated_text:
                        logger.warning(f"Empty response for prompt {prompt_id}, attempt {attempt + 1}")
                        if attempt < max_retries - 1:
                            time.sleep(1)
                            continue
                    
                    # Try multiple extraction strategies
                    mc_questions = self._extract_mc_questions(generated_text)
                    if mc_questions:
                        logger.info(f"Successfully generated mc questions for prompt {prompt_id}")
                        return mc_questions
                    else:
                        logger.warning(f"Failed to parse JSON for prompt {prompt_id}, attempt {attempt + 1}. Response: {generated_text[:200]}")
                        if attempt < max_retries - 1:
                            time.sleep(1)
                            continue
                else:
                    logger.error(f"xAI API error: {response.status_code}, {response.text}")
                    if attempt < max_retries - 1:
                        time.sleep(2)
                        continue
                        
            except requests.exceptions.Timeout:
                logger.warning(f"Timeout generating mc questions {prompt_id}, attempt {attempt + 1}")
                if attempt < max_retries - 1:
                    time.sleep(2)
                    continue
            except Exception as e:
                logger.error(f"Error generating mc questions {prompt_id}, attempt {attempt + 1}: {str(e)}")
                if attempt < max_retries - 1:
                    time.sleep(1)
                    continue
        
        logger.error(f"Failed to generate mc questions for prompt {prompt_id} after {max_retries} attempts")
        return None
    
    def _extract_mc_questions(self, text: str) -> Optional[List[Any]]:
        """Extract mc questions from text using multiple strategies."""
        if not text:
            return None
        
        try:
            # Remove markdown code blocks if present
            text_clean = re.sub(r'```json\s*', '', text)
            text_clean = re.sub(r'```\s*', '', text_clean)
            text_clean = text_clean.strip()
            
            # Find JSON object
            start_idx = text_clean.find('{')
            end_idx = text_clean.rfind('}')
            
            if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                json_str = text_clean[start_idx:end_idx + 1]
                data = json.loads(json_str)
                
                if isinstance(data, dict) and "multiple_choice_questions" in data:
                    mc_questions = data["multiple_choice_questions"]
                    #mc questions is a list of dictionaries, each dictionary contains a question and a list of answers
                    if isinstance(mc_questions, list) and len(mc_questions) > 0:
                        return mc_questions
                    else:
                        return None
        except json.JSONDecodeError:
            logger.error(f"Invalid JSON response: {text}")
            return None
        except Exception:
            logger.error(f"Error extracting mc questions: {text}")
            return None
        return None


def generate_mc_questions_worker(args: tuple) -> tuple:
    """Worker function for multiprocessing."""
    question, solution, prompt_id, api_key, model = args
    
    generator = QuestionGenerator(api_key=api_key, model=model)
    mc_questions = generator.generate_mc_questions(question, solution, prompt_id)
    
    return (prompt_id, mc_questions)

# Parallelize 20 workers simultaneously to generate mc questions off of ctf_dataset.json
def generate_mc_questions_parallel(api_key: str = None, model: str = "grok-4-fast-reasoning") -> List[Tuple[int, Optional[List[Any]]]]:
    """Generate mc questions in parallel using multiple workers."""
    with open("ctf_dataset.json", "r") as f:
        dataset = json.load(f)
    # dataset is a list of json objects, each object contains a question and a solution
    prompt_ids = list(range(len(dataset)))
    args = [(dataset[i]["question"], dataset[i]["solution"], prompt_ids[i], api_key, model) for i in range(len(dataset))]
    with multiprocessing.Pool(20) as p:
        results = p.map(generate_mc_questions_worker, args)
    # results is a list of tuples, each tuple contains a prompt_id and a list of mc questions
    return results

if __name__ == "__main__":
    results = generate_mc_questions_parallel()
    # Extract all mc questions, filtering out None values
    all_mcqs = []
    for prompt_id, mc_questions in results:
        if mc_questions is not None:
            all_mcqs.extend(mc_questions)

    # Save all mc questions to a single file "mcqs.json"
    with open("mcqs.json", "w") as f:
        json.dump(all_mcqs, f, indent=2)
    logger.info(f"Successfully generated {len(all_mcqs)} mc questions from {len(results)} prompts")