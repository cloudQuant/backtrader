# Current-fork authoring rules

- A direct `bt.Strategy` subclass may read `self.p`, `self.datas`, broker, and
  data aliases in its own `__init__` without calling `super().__init__()`. The
  current fork initializes these before dispatching the user initializer.
- A custom parent strategy or cooperative mixin may own initialization; follow
  that class's MRO contract and call `super()` where required.
- Multi-data and multi-timeframe indicators must be bound to their actual input
  feed/clock. Do not silently align with forward-fill.
- Build indicators in `__init__`; trade in `next`. Avoid future indexing and
  incomplete higher-timeframe bars.
- Use only offline registered data and analyzers included in the generated
  profile. Live stores/brokers are outside P0.
