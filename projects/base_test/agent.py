
class Agent:
    def __init__(self, model, name, description, instruction, tools):
        self.model = model
        self.name = name
        self.description = description
        self.instruction = instruction
        self.tools = tools

    def config(self):
        print(f"Model: {self.model}")
        print(f"Name: {self.name}")
        print(f"Description: {self.description}")
        print(f"Instruction: {self.instruction}")
        print(f"Tools: {self.tools}")

    @property
    def model(self):
        return self._model
    @model.setter
    def model(self, value):
        if not isinstance(value, str):
            raise ValueError("Model must be a string")
        self._model = value


a = Agent(model="LiteLlm(model=get_model_name())", name="test_agent", description="这是一个测试智能体", instruction="这是一个测试智能体", tools=[])
a.config()
