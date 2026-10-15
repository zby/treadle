import sys; sys.path.insert(0, 'shared')
from pydantic_ai.function_signature import FunctionSignature
from catalog import CATALOG
P = {'type':'object','properties':{'task':{'type':'string'}},'required':['task'],'additionalProperties':False}
sigs=[FunctionSignature.from_schema(name=a.name, parameters_schema=P, return_schema=(a.output_type.model_json_schema() if a.output_type else {'type':'string'})) for a in CATALOG]
c=FunctionSignature.get_conflicting_type_names(sigs)
parts=['import asyncio\nfrom typing import Any, TypedDict, NotRequired, Literal']
parts+=FunctionSignature.render_type_definitions(sigs,c)
parts+=[s.render('raise NotImplementedError()', is_async=True, conflicting_type_names=c) for s in sigs]
print('\n\n'.join(parts))
