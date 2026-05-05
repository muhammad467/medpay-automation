---
tags:
- sentence-transformers
- sentence-similarity
- feature-extraction
- generated_from_trainer
- dataset_size:14432
- loss:TripletLoss
base_model: intfloat/multilingual-e5-base
widget:
- source_sentence: Тиреоглобулин (ТГ, TG)
  sentences:
  - Инсулин, концентрация в условных единицах в сыворотке или плазме крови
  - Магний, массовая концентрация в сыворотке или плазме крови
  - Тиреоглобулин, массовая концентрация в сыворотке или плазме крови
- source_sentence: Бактериальный посев грудного молока на стерильность
  sentences:
  - Волчаночный антикоагулянт, скрининговый тест с кварцевым активатором в свободной
    от тромбоцитов плазме
  - Gardnerella vaginalis ДНК, обнаружение в отделяемом слизистой влагалища методом
    амплификации нуклеиновых кислот
  - Бактериологический посев крови на стерильность
- source_sentence: Генитальный герпес
  sentences:
  - Исследование кала на скрытую кровь
  - Антитела IgG к Herpes simplex virus 1 и 2, титр в сыворотке крови
  - Витамин D общий и его метаболиты, массовая концентрация в сыворотке или плазме
    крови
- source_sentence: Витамин D3 (25 ОН)
  sentences:
  - Витамин D общий и его метаболиты, массовая концентрация в сыворотке или плазме
    крови
  - Toxoplasma gondii ДНК, обнаружение в любой пробе методом амплификации нуклеиновых
    кислот
  - Антитела IgM к Herpes simplex virus 1 и ​2, обнаружение в сыворотке крови
- source_sentence: Селезенка
  sentences:
  - C-реактивный белок, массовая концентрация в сыворотке или плазме крови методом
    латекс-агглютинации
  - Ультразвуковое исследование селезенки трансабдоминальное
  - Рентгенография таза
pipeline_tag: sentence-similarity
library_name: sentence-transformers
---

# SentenceTransformer based on intfloat/multilingual-e5-base

This is a [sentence-transformers](https://www.SBERT.net) model finetuned from [intfloat/multilingual-e5-base](https://huggingface.co/intfloat/multilingual-e5-base). It maps sentences & paragraphs to a 768-dimensional dense vector space and can be used for retrieval.

## Model Details

### Model Description
- **Model Type:** Sentence Transformer
- **Base model:** [intfloat/multilingual-e5-base](https://huggingface.co/intfloat/multilingual-e5-base) <!-- at revision d128750597153bb5987e10b1c3493a34e5a4502a -->
- **Maximum Sequence Length:** 512 tokens
- **Output Dimensionality:** 768 dimensions
- **Similarity Function:** Cosine Similarity
- **Supported Modality:** Text
<!-- - **Training Dataset:** Unknown -->
<!-- - **Language:** Unknown -->
<!-- - **License:** Unknown -->

### Model Sources

- **Documentation:** [Sentence Transformers Documentation](https://sbert.net)
- **Repository:** [Sentence Transformers on GitHub](https://github.com/huggingface/sentence-transformers)
- **Hugging Face:** [Sentence Transformers on Hugging Face](https://huggingface.co/models?library=sentence-transformers)

### Full Model Architecture

```
SentenceTransformer(
  (0): Transformer({'transformer_task': 'feature-extraction', 'modality_config': {'text': {'method': 'forward', 'method_output_name': 'last_hidden_state'}}, 'module_output_name': 'token_embeddings', 'architecture': 'XLMRobertaModel'})
  (1): Pooling({'embedding_dimension': 768, 'pooling_mode': 'mean', 'include_prompt': True})
  (2): Normalize({})
)
```

## Usage

### Direct Usage (Sentence Transformers)

First install the Sentence Transformers library:

```bash
pip install -U sentence-transformers
```
Then you can load this model and run inference.
```python
from sentence_transformers import SentenceTransformer

# Download from the 🤗 Hub
model = SentenceTransformer("sentence_transformers_model_id")
# Run inference
sentences = [
    'Селезенка',
    'Ультразвуковое исследование селезенки трансабдоминальное',
    'Рентгенография таза',
]
embeddings = model.encode(sentences)
print(embeddings.shape)
# [3, 768]

# Get the similarity scores for the embeddings
similarities = model.similarity(embeddings, embeddings)
print(similarities)
# tensor([[ 1.0000,  0.8908,  0.0044],
#         [ 0.8908,  1.0000, -0.0832],
#         [ 0.0044, -0.0832,  1.0000]])
```
<!--
### Direct Usage (Transformers)

<details><summary>Click to see the direct usage in Transformers</summary>

</details>
-->

<!--
### Downstream Usage (Sentence Transformers)

You can finetune this model on your own dataset.

<details><summary>Click to expand</summary>

</details>
-->

<!--
### Out-of-Scope Use

*List how the model may foreseeably be misused and address what users ought not to do with the model.*
-->

<!--
## Bias, Risks and Limitations

*What are the known or foreseeable issues stemming from this model? You could also flag here known failure cases or weaknesses of the model.*
-->

<!--
### Recommendations

*What are recommendations with respect to the foreseeable issues? For example, filtering explicit content.*
-->

## Training Details

### Training Dataset

#### Unnamed Dataset

* Size: 14,432 training samples
* Columns: <code>anchor</code>, <code>positive</code>, and <code>negative</code>
* Approximate statistics based on the first 1000 samples:
  |         | anchor                                                                            | positive                                                                         | negative                                                                          |
  |:--------|:----------------------------------------------------------------------------------|:---------------------------------------------------------------------------------|:----------------------------------------------------------------------------------|
  | type    | string                                                                            | string                                                                           | string                                                                            |
  | details | <ul><li>min: 4 tokens</li><li>mean: 11.98 tokens</li><li>max: 80 tokens</li></ul> | <ul><li>min: 6 tokens</li><li>mean: 19.8 tokens</li><li>max: 50 tokens</li></ul> | <ul><li>min: 6 tokens</li><li>mean: 20.02 tokens</li><li>max: 64 tokens</li></ul> |
* Samples:
  | anchor                                       | positive                                                                                                 | negative                                                                                             |
  |:---------------------------------------------|:---------------------------------------------------------------------------------------------------------|:-----------------------------------------------------------------------------------------------------|
  | <code>Цитология (ПАП-тест)</code>            | <code>Цитологическое исследование соскобов шейки матки и цервикального канала по системе Bethesda</code> | <code>Гомоцистеин в сыворотке или плазме крови</code>                                                |
  | <code>Цитология (ПАП-тест)</code>            | <code>Цитологическое исследование соскобов шейки матки и цервикального канала по системе Bethesda</code> | <code>Гликозилированный гемоглобин (HbA1c)</code>                                                    |
  | <code>Анализ мочи на желчные пигменты</code> | <code>Желчные пигменты в моче</code>                                                                     | <code>Антитела IgG к Ascaris lumbricoides, концентрация в условных единицах в сыворотке крови</code> |
* Loss: [<code>TripletLoss</code>](https://sbert.net/docs/package_reference/sentence_transformer/losses.html#tripletloss) with these parameters:
  ```json
  {
      "distance_metric": "TripletDistanceMetric.COSINE",
      "triplet_margin": 0.5
  }
  ```

### Training Hyperparameters
#### Non-Default Hyperparameters

- `per_device_train_batch_size`: 32
- `num_train_epochs`: 4
- `learning_rate`: 2e-05
- `warmup_steps`: 180
- `fp16`: True

#### All Hyperparameters
<details><summary>Click to expand</summary>

- `per_device_train_batch_size`: 32
- `num_train_epochs`: 4
- `max_steps`: -1
- `learning_rate`: 2e-05
- `lr_scheduler_type`: linear
- `lr_scheduler_kwargs`: None
- `warmup_steps`: 180
- `optim`: adamw_torch_fused
- `optim_args`: None
- `weight_decay`: 0.0
- `adam_beta1`: 0.9
- `adam_beta2`: 0.999
- `adam_epsilon`: 1e-08
- `optim_target_modules`: None
- `gradient_accumulation_steps`: 1
- `average_tokens_across_devices`: True
- `max_grad_norm`: 1.0
- `label_smoothing_factor`: 0.0
- `bf16`: False
- `fp16`: True
- `bf16_full_eval`: False
- `fp16_full_eval`: False
- `tf32`: None
- `gradient_checkpointing`: False
- `gradient_checkpointing_kwargs`: None
- `torch_compile`: False
- `torch_compile_backend`: None
- `torch_compile_mode`: None
- `use_liger_kernel`: False
- `liger_kernel_config`: None
- `use_cache`: False
- `neftune_noise_alpha`: None
- `torch_empty_cache_steps`: None
- `auto_find_batch_size`: False
- `log_on_each_node`: True
- `logging_nan_inf_filter`: True
- `include_num_input_tokens_seen`: no
- `log_level`: passive
- `log_level_replica`: warning
- `disable_tqdm`: False
- `project`: huggingface
- `trackio_space_id`: None
- `trackio_bucket_id`: None
- `trackio_static_space_id`: None
- `per_device_eval_batch_size`: 8
- `prediction_loss_only`: True
- `eval_on_start`: False
- `eval_do_concat_batches`: True
- `eval_use_gather_object`: False
- `eval_accumulation_steps`: None
- `include_for_metrics`: []
- `batch_eval_metrics`: False
- `save_only_model`: False
- `save_on_each_node`: False
- `enable_jit_checkpoint`: False
- `push_to_hub`: False
- `hub_private_repo`: None
- `hub_model_id`: None
- `hub_strategy`: every_save
- `hub_always_push`: False
- `hub_revision`: None
- `load_best_model_at_end`: False
- `ignore_data_skip`: False
- `restore_callback_states_from_checkpoint`: False
- `full_determinism`: False
- `seed`: 42
- `data_seed`: None
- `use_cpu`: False
- `accelerator_config`: {'split_batches': False, 'dispatch_batches': None, 'even_batches': True, 'use_seedable_sampler': True, 'non_blocking': False, 'gradient_accumulation_kwargs': None}
- `parallelism_config`: None
- `dataloader_drop_last`: False
- `dataloader_num_workers`: 0
- `dataloader_pin_memory`: True
- `dataloader_persistent_workers`: False
- `dataloader_prefetch_factor`: None
- `remove_unused_columns`: True
- `label_names`: None
- `train_sampling_strategy`: random
- `length_column_name`: length
- `ddp_find_unused_parameters`: None
- `ddp_bucket_cap_mb`: None
- `ddp_broadcast_buffers`: False
- `ddp_static_graph`: None
- `ddp_backend`: None
- `ddp_timeout`: 1800
- `fsdp`: []
- `fsdp_config`: {'min_num_params': 0, 'xla': False, 'xla_fsdp_v2': False, 'xla_fsdp_grad_ckpt': False}
- `deepspeed`: None
- `debug`: []
- `skip_memory_metrics`: True
- `do_predict`: False
- `resume_from_checkpoint`: None
- `warmup_ratio`: None
- `local_rank`: -1
- `prompts`: None
- `batch_sampler`: batch_sampler
- `multi_dataset_batch_sampler`: proportional
- `router_mapping`: {}
- `learning_rate_mapping`: {}

</details>

### Training Logs
| Epoch  | Step | Training Loss |
|:------:|:----:|:-------------:|
| 0.1109 | 50   | 0.4084        |
| 0.2217 | 100  | 0.1495        |
| 0.3326 | 150  | 0.0488        |
| 0.4435 | 200  | 0.0352        |
| 0.5543 | 250  | 0.0339        |
| 0.6652 | 300  | 0.0294        |
| 0.7761 | 350  | 0.0286        |
| 0.8869 | 400  | 0.0294        |
| 0.9978 | 450  | 0.0317        |
| 1.1086 | 500  | 0.0161        |
| 1.2195 | 550  | 0.0159        |
| 1.3304 | 600  | 0.0145        |
| 1.4412 | 650  | 0.0153        |
| 1.5521 | 700  | 0.0179        |
| 1.6630 | 750  | 0.0139        |
| 1.7738 | 800  | 0.0143        |
| 1.8847 | 850  | 0.0158        |
| 1.9956 | 900  | 0.0121        |
| 2.1064 | 950  | 0.0111        |
| 2.2173 | 1000 | 0.0097        |
| 2.3282 | 1050 | 0.0084        |
| 2.4390 | 1100 | 0.0081        |
| 2.5499 | 1150 | 0.0084        |
| 2.6608 | 1200 | 0.0097        |
| 2.7716 | 1250 | 0.0080        |
| 2.8825 | 1300 | 0.0094        |
| 2.9933 | 1350 | 0.0089        |
| 3.1042 | 1400 | 0.0057        |
| 3.2151 | 1450 | 0.0067        |
| 3.3259 | 1500 | 0.0055        |
| 3.4368 | 1550 | 0.0068        |
| 3.5477 | 1600 | 0.0059        |
| 3.6585 | 1650 | 0.0064        |
| 3.7694 | 1700 | 0.0075        |
| 3.8803 | 1750 | 0.0071        |
| 3.9911 | 1800 | 0.0063        |


### Training Time
- **Training**: 14.2 minutes

### Framework Versions
- Python: 3.12.13
- Sentence Transformers: 5.4.1
- Transformers: 5.7.0
- PyTorch: 2.10.0+cu128
- Accelerate: 1.13.0
- Datasets: 4.8.5
- Tokenizers: 0.22.2

## Citation

### BibTeX

#### Sentence Transformers
```bibtex
@inproceedings{reimers-2019-sentence-bert,
    title = "Sentence-BERT: Sentence Embeddings using Siamese BERT-Networks",
    author = "Reimers, Nils and Gurevych, Iryna",
    booktitle = "Proceedings of the 2019 Conference on Empirical Methods in Natural Language Processing",
    month = "11",
    year = "2019",
    publisher = "Association for Computational Linguistics",
    url = "https://arxiv.org/abs/1908.10084",
}
```

#### TripletLoss
```bibtex
@misc{hermans2017defense,
    title={In Defense of the Triplet Loss for Person Re-Identification},
    author={Alexander Hermans and Lucas Beyer and Bastian Leibe},
    year={2017},
    eprint={1703.07737},
    archivePrefix={arXiv},
    primaryClass={cs.CV}
}
```

<!--
## Glossary

*Clearly define terms in order to be accessible across audiences.*
-->

<!--
## Model Card Authors

*Lists the people who create the model card, providing recognition and accountability for the detailed work that goes into its construction.*
-->

<!--
## Model Card Contact

*Provides a way for people who have updates to the Model Card, suggestions, or questions, to contact the Model Card authors.*
-->