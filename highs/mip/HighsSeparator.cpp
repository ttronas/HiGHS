/* * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * */
/*                                                                       */
/*    This file is part of the HiGHS linear optimization suite           */
/*                                                                       */
/*    Available as open-source under the MIT License                     */
/*                                                                       */
/* * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * * */
#include "mip/HighsSeparator.h"

#include <string>

#include "HighsMipSolverData.h"
#include "mip/HighsCutPool.h"
#include "mip/HighsLpRelaxation.h"
#include "mip/HighsMipSolver.h"
#include "mip/MipTimer.h"

HighsSeparator::HighsSeparator(const HighsMipSolver& mipsolver,
                               const std::string& name)
    : numCutsFound(0), numCalls(0) {
  if (name == kTableauSepaString)
    this->clockIndex = kMipClockTableauSepa;
  else if (name == kPathAggrSepaString)
    this->clockIndex = kMipClockPathAggrSepa;
  else if (name == kModKSepaString)
    this->clockIndex = kMipClockModKSepa;
  else if (name == kImplboundSepaString)
    this->clockIndex = kMipClockImplboundSepa;
  else if (name == kCliqueSepaString)
    this->clockIndex = kMipClockCliqueSepa;
  else
    this->clockIndex = kMipClockImplboundSepa;
}

void HighsSeparator::run(HighsLpRelaxation& lpRelaxation,
                         HighsLpAggregator& lpAggregator,
                         HighsTransformedLp& transLp, HighsCutPool& cutpool) {
  ++numCalls;
  HighsInt currNumCuts = cutpool.getNumCuts();

  const bool doProfile = !lpRelaxation.getMipSolver().mipdata_->parallelLockActive() &&
                         lpRelaxation.getMipSolver().profiling_->mip_;
  if (doProfile) lpRelaxation.getMipSolver().profiling_->start(clockIndex);
  separateLpSolution(lpRelaxation, lpAggregator, transLp, cutpool);
  if (doProfile) lpRelaxation.getMipSolver().profiling_->stop(clockIndex);

  numCutsFound += cutpool.getNumCuts() - currNumCuts;
}
